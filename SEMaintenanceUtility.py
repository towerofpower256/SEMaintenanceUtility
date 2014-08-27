"""
Space Engineers Server Maintenance utility
By David McDonald - Started 12/07/2014

This script is to load a SpaceEngineers save and perform maintenance & cleanup tasks such as;
 - Removal of unneeded objects, multiple classifications of "unneeded"
 - Removal of empty factions & factions that don't own anything
 - Restore asteroids that no one is near (in progress)

It requires a fair chunk of RAM at times because it has to load & parse the large SE save file. Some of those get up to 100MB.

v1.1 15/07/2014
 - Added Junk mode, removing everything without a reaction, regardless of fuel or status.
 - Considered pruning factions without a leader but you might get into strife over factions getting along without a leader,
	 suddenly having base turrets turn on friendlies. Won't do that.
 - Added function to remove all free-floating objects. Doesn't do corpses though, they are more complicated
 - Added whatif mode, like Powershell, doesn't make any changes but tells you what it'll do. Good for debugging
 - Added function to remove junk players, players that don't own anything. Also removes them from factions.
	Considered using players with the <IsDead> attribute True, but that would screw up ownership. 
	Might consider another mode that removes "dead" players and sets ownership of their stuff to "nobody".

v1.1.1 16/07/2014
 - Fixed up Player pruning. Removes player from the FactionPlayer and FactionRequests tables
 - Fixed up Faction pruning. Stopped removing factions who's members don't own anything, will only clear away empty factions now. The player pruner should make this more viable
	Also removes factions from FactionRelations & FactionRequests
	
v1.2
 - Added function to kill movement and inertia
 - Added function to soft and hard turn off assemblers and refineries
 - Discovered that Rotors are joined based on proximity, no by an ID. To avoid damage until a solution is found, no object with a stator or a rotor will be removed.
 - Modified PlayerPrune to: Owns Nothing & (Not in a faction OR IsDead). This will remove all junk dead player entries as well as player entries for those that join the server, play for 20secs then leave
 - Added function to remove NPC ships
 
v1.2.1
 - Added in "barebeacon" cleanup function for when you want to keep things with a beacon on it, regardless of power or anything else
 - Added in --ignore-joint function to ignore the restriction on removing things with joints. USE WITH CAUTION.
 
 v1.3
 - Added support for batteries
 - Refined NPC detection, now looks for DampenersEnabled == 'true'
 
 v1.3.1
 - Unicode faction & player names no longer cause exceptions
 - Added --full-clean option to do --cleanup-objects dead --cleanup-items --prune-players --prune-factions --disable-factories soft
 
 v1.3.2
 - Rewrote for Python 3, should resolve unicode issues
 - Added saving & respawning of asteroids (--save-asteroids & --respawn-asteroids)
 - Removed cleanup modes, replaced with --cleanup-unpowered, --cleanup-include-solar, --cleanup-missing-attrib and --cleanup-missing-subtype
 - Now gives an instructive message if you just double click on the utility
 - Added support for detecting Pistons as a joint
 - Added support for semi-auto batteries
 
 v1.3.3
 - Added logging
 - Added some scripts to the dist folder to make things more user-friendly
 - Added feature to try to determine a cubegrids name based on attached beacons and antennae
 - Removed counting a semi-auto battery as a valid power source as it doesn't always work. Will just stick to detecting "ProducerEnabled" and a charge level above 0
 
 v1.3.4
 - Added more logging, is now more descriptive as to why it's doing something
 - To allow for intentionally disabled ships, changed --cleanup-unpowered to just detect for fueled reactors and charged batteries, regardless if it's disabled or charging. As long as it has the potential for power, it'll be safe.
 - Changed backup naming to <save>.backup and <save>.<timestamp>.backup
 - Fixed up player pruning, was having issues detecting factionless players
 
 v1.3.5
 - Added in more Unicode handing
 - Corrected NPC removal function, was using some old Attrib finding code that an SE update broke
 
 v1.3.6
 - Adjusted XPrint calls for greater error handling
 - Fixed to handle blank / empty names for beacons & antennae
 
 v1.3.7
 - Fixed some issues with NPC detection
 - Added function to remove Refinery queues. They don't do much but as of SE 01.043, can explode into an indefinite amount of entries, causing lag and large save sizes
 - Added ship name detection with new ship naming under the Info tab
 - Updated Disable Factories to work with new SE factory node layout
 
"""

import xml.etree.ElementTree as ET #Used to read the SE save files
import argparse #Used for CLI arguments
import os #For file system checks & snapshot file working
import shutil #For copying files to backups
import datetime #For timestamps
import sys #for propper sys.exit()
import traceback #For some error handling verbosity

#########################################
### Functions ###########################
#########################################

#Function to open the log
def OpenLog():
	#Define the filename
	logfoldername = "./semu_logs/"
	logfilename = "log %s.txt"%datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
	
	if not os.path.isdir(logfoldername):
		#and make it if it doesn't
		os.makedirs(logfoldername)
	
	#make the log
	f = open(logfoldername+logfilename, 'w')
	f.close()
	
	return logfoldername+logfilename

#Function to write to the log
def XPrint(*msg):
	#Open the log. Relies on the variable above this scope, logfilename, to be set
	f = open(logfilename, 'a')
	
	try: #Doing some error handling, fucking unicode...
		#Try to do some conversion, in case it isn't a string
		lmsg = []
		for m in msg:
			"""
			#print(type(m))
			if type(m) == str: #If it's a string, make sure it's not a unicode one
				try:
					lmsg.append(m.encode('utf-8', 'ignore').decode('ascii')) #Try to recover from Unicode
				except: #Fuck your shit Unicode, fuck it right in the mouth
					lmsg.append("<unicode failed>") #Just add something, it failed
			else: #Must be something else. Either way, try to add it as a string
				lmsg.append("%s"%m)
			"""
			
			lmsg.append(SafeString(m))
			
		#End string building loop
		
		msg = "%s: %s"%(datetime.datetime.now().strftime("%H:%M:%S"), "".join(lmsg))
	
	except: #In case building the string breaks
		msg = "%s: %s"%(datetime.datetime.now().strftime("%H:%M:%S"), traceback.print_exc())
	
	#Display message on screen
	print(msg)
	
	#Write to the log
	f.write(msg+"\r")
	
	#Close log
	f.close()

#Got shitty with crazy UTF characters breaking things. This function will attempt to make sense of it and return "<unicode>" if it breaks
def SafeString(input):
	if type(input) == str: #If it's a string, make sure it's not a unicode one
		try:
			return(input.encode('utf-8', 'ignore').decode('ascii')) #Try to recover from Unicode
		except: #Fuck your shit Unicode, fuck it right in the mouth
			return("<crazy unicode>") #Just add something, it failed
	else: #Must be something else. Either way, try to add it as a string
		return(str(input))

#Function to possibly find a CubeGrid's name. Search for the name(s) of Antennae and Beacons
def FindObjectName(objectcluster):
	foundnames = []
	
	for object in objectcluster:
		if object.find('DisplayName') != None: #if a name has been specified under the Info tab
			if object.find('DisplayName').text != None: #Blank name, ignore it
				foundnames.append(SafeString(object.find('DisplayName').text))
			
		for block in object.find('CubeBlocks'):
			attrib = FindAttrib(block)
			if attrib == "MyObjectBuilder_Beacon" or attrib == "MyObjectBuilder_RadioAntenna":
				#If it hasn't been given a custom name, then it's either called "Antenna" or "Beacon"
				if block.find('CustomName') == None:
					if attrib == "MyObjectBuilder_Beacon":
						foundnames.append("Beacon")
					if attrib == "MyObjectBuilder_RadioAntenna":
						foundnames.append("Antenna")
				else: #If it has a custom name
					n = block.find('CustomName').text
					if n == None: #If it has a blank name, use the default block names
						if attrib == "MyObjectBuilder_Beacon":
							foundnames.append("Beacon")
						if attrib == "MyObjectBuilder_RadioAntenna":
							foundnames.append("Antenna")
					else: 
						foundnames.append(SafeString(n))
	#End block loop
	
	#Had unicode checking here, moved to SafeString function
	
	return " / ".join(foundnames)

#Function to remove the Queue node from refineries
def RemoveRefineryQueue(objectcluster):
	for object in objectcluster:
		for cube in object.find('CubeBlocks'):
			if cube.find('Queue') != None and FindAttrib(cube) == "MyObjectBuilder_Refinery": #if there's a Queue node and it's a refinery, remove it
				XPrint("Removing refinery queue on entity: ", object.find('EntityId').text)
				cube.remove(cube.find('Queue'))


#Function to see if a node has an attrib, and then return it. Return empty string if not found
def FindAttrib(objnode):
	if len(objnode.attrib.values()) > 0:
		return list(objnode.attrib.values())[0]
		
	
	#Made it out to here, no attrib
	return ""

#Function to fetch what faction a playerID belongs to
def FindPlayerFaction(factiontree, playerID):
	for faction in factiontree:
		for member in faction.find('Members'):
			if member.find('PlayerId').text == playerID:
				return faction #Return the node
				
	#Made it out here, the player musn't be part of a faction
	return None

#Function to return the XMl node for a specific node with a matching ID
#Mainly used for finding entities in SectorObjects
def FindByID(rootnode, idfieldname, idtosearchfor):
	for node in rootnode:
		if node.find(idfieldname) == None: #Field not found in this node
			continue #Move on to the next node
			
		if node.find(idfieldname).text == idtosearchfor:
			return node
	
	#If it made it out of the loop, didn't find entity
	return None

#Function to get the name of a floating object
def GetFloatingItemName(objnode):
	#try:
		return "%s : %s"%(FindAttrib(objnode.find('Item').find('PhysicalContent')).replace("MyObjectBuilder_", ""), objnode.find('Item').find('PhysicalContent').find('SubtypeName').text) #type : name e.g. Ore : Iron
	#except: #Just in case it fucks up
		return ""
	
#Function to map out the entities all joined by rotors, known as a cluster
#attrib:MyObjectBuilder_MotorRotor connects to attrib:MyObjectBuilder_MotorStator, stator's having the numbers on them
#BROKEN - FIX IT LATER
def MapObjectCluster(sectorobjectsnode, objnode):
	entitymap = [objnode] #Final table of entity ID's that will be returned
	entityqueue = [objnode] #Queue list of entites to be processed
	
	#Add the initial entity
	entitymap.append(objnode)
	
	#Begin the loop!
	
	while len(entityqueue) > 0: #While the queue isn't empty
		ent = entityqueue.pop()
		
		if ent in entitymap: #If there comes a time where multiple rotors can join 2 objects together, I've got it covered
			continue
		
		entitymap.append(ent.find('EntityId').text)
		cubes = ent.find('CubeBlocks')
		for cube in cubes:
			if cube.find('SubtypeName') == "LargeRotor" or cube.find('SubtypeName') == "SmallRotor":
				entityqueue.append(FindByID(sectorobjectsnode, "EntityId", cube.find('EntityId').text)) #Add that entity to the list
				entitymap.append(FindByID(sectorobjectsnode, "EntityId", cube.find('EntityId').text))
				
	return entitymap

#Function to find out of an entity has a rotor, stator, pistontop or pistonbase
def HasJoint(objectcluster):
	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			attrib = FindAttrib(block)
			if attrib == "MyObjectBuilder_MotorRotor" or attrib == "MyObjectBuilder_MotorStator" or attrib == "MyObjectBuilder_PistonBase" or attrib == "MyObjectBuilder_PistonTop":
				return True #Entity has a joint
			
			
			"""
			if len(block.attrib.values()) > 0: #If it has an attribute
				if block.attrib.values()[0] == "MyObjectBuilder_MotorRotor" or block.attrib.values()[0] == "MyObjectBuilder_MotorStator" or block.attrib.values()[0] == "MyObjectBuilder_PistonBase" or block.attrib.values()[0] == "MyObjectBuilder_PistonTop":
					return True #Entity has a joint
			"""
	
	#Made it out here, musn't have a joint
	return False
	
#Function to remove all inertia
def KillClusterInertia(objectcluster):
	for object in objectcluster:
		object.find('LinearVelocity').attrib["x"] = "0"
		object.find('LinearVelocity').attrib["z"] = "0"
		object.find('LinearVelocity').attrib["y"] = "0"
		
		object.find('AngularVelocity').attrib["x"] = "0"
		object.find('AngularVelocity').attrib["y"] = "0"
		object.find('AngularVelocity').attrib["z"] = "0"
#End KillClsterIntertia
		
#Function to decide whether to remove an object cluster
def DoIRemoveThisCluster(objectcluster, findattribs, findsubtypes, musthavepower = False, allowsolar = False):
	#Define checks
	haspower = False
	attribmatch = False
	subtypematch = False
	neededblock = False
	
	#Begin checking through object blocks
	for object in objectcluster:
		XPrint("Checking entity:", object.find("EntityId").text, " ", FindObjectName(objectcluster))
		for block in object.find('CubeBlocks'):
			attrib = FindAttrib(block)
			#XPrint("'" + attrib + "'")
			subtype = block.find('SubtypeName').text
			
			#Power checks
			if attrib == "MyObjectBuilder_Reactor" and musthavepower == True: #If it's a reactor
				#Is it fueled? No matter what, if there's an item in a reactor, it's fueled. Possibility of fucking-up if SE starts allowing non-fuel into a reactor in future versions.
				if len(block.find('Inventory').find('Items')) > 0:
					XPrint("- Found fueled reactor")
					haspower = True #Has power, even if it's disabled
				else:
					XPrint("- Found empty reactor")
			#End reactor check
				
			if attrib == "MyObjectBuilder_BatteryBlock" and musthavepower == True: #If it's a battery
				if block.find('CurrentStoredPower').text != '0':
					XPrint("- Found charged battery")
					haspower = True #Battery is juicing the juices, but may be disabled
				else:
					XPrint("- Found dead battery")
			#End Battery check
			
			if attrib == "MyObjectBuilder_SolarPanel" and allowsolar == True and musthavepower == True: #If it's a battery and we're checking for power AND its been specified that we should include solar panels
				if block.find('Enabled').text == "true": #If by some miracle, they've managed to disable the panel
					XPrint("- Found solar panel, including in power check")
					haspower = True #Include it in the power check. I remind you that THIS IS NOT COUNTED BY DEFAULT.
					
			#Attrib & subtype checks
			if (subtype in findsubtypes):
				XPrint("- Found wanted subtype: "+subtype)
				neededblock = True #It has a block that we're after
				
			if (attrib in findattribs):
				XPrint("- Found wanted attribute: "+attrib)
				neededblock = True
			
		#End of block loop
	#End of cluster loop
	
	#XPrint("-")
	#XPrint(haspower == True or musthavepower == False)
	#XPrint(neededblock == True or (len(findattribs) == 0 and len(findsubtypes) == 0))
	
	if (haspower == True or musthavepower == False) and (neededblock == True or (len(findattribs) == 0 and len(findsubtypes) == 0)): # If (haspower OR power not needed) AND (found needed block OR no blocks to search for)
		return False #Must be good, leave it alone
	else:
		return True #Blast it
	

#Function to loop through an object cluster and disable factories, hard or soft
def DisableFactories(objectcluster, mode):
	#XPrint("Checking for factories")
	#XPrint(objectcluster)
	#XPrint(mode)
	for object in objectcluster:
		for block in object.find('CubeBlocks'):
			attrib = FindAttrib(block)
			if attrib == "MyObjectBuilder_Refinery": #Is a refinery
				#XPrint("Found Refinery")
				if (mode == 'soft' and len(block.find('InputInventory').find('Items')) == 0) or mode == 'hard': #If the mode is 'soft' and there's nothing inside to be refined; or it's 'hard' mode to turn it off regardless
					block.find('Enabled').text = "false" #Turn it off
					XPrint("Turning off refinery on entity: ", object.find('EntityId').text)
					
			if attrib == "MyObjectBuilder_Assembler": #Is an assembler
				#XPrint("Found Assembler")
				#Well aint that some shit, SE removes the 'Queue' node if there's nothing in the queue instead of leaving an empty node...
				if (mode == 'soft' and block.find('Queue') == None) or mode == 'hard': #If the mode is 'soft' and there's nothing in the queue; or it's 'hard' mode to turn it off regardless
					block.find('Enabled').text = "false" #Turn it off
					XPrint("Turning off assembler on entity: " + object.find('EntityId').text)
						

#Function to get a list of players that own at least a part of this object cluster
def GetClusterOwners(objectcluster):
	shareholders = []
	
	for object in objectcluster:
		for cube in object.find('CubeBlocks'):
			if cube.find('Owner') != None: #If there is an Owner tag on this block
				if not cube.find('Owner').text in shareholders: #If this owner isn't currently recorded
					shareholders.append(cube.find('Owner').text) #Add it to the list
					
	return shareholders

#Function to get members of a faction
def GetFactionMembers(factionNode):
	members = []
	
	for member in factionNode.find('Members'):
		members.append(member.find('PlayerId').text)
	
	return members

#Function to determine if the cluster is an NPC ship or not
def IsClusterAnNPC(objectcluster):
	namestofind = ["Private Sail", "Business Shipment", "Commercial Freighter", "Mining Carriage", "Mining Transport", "Mining Hauler", "Military Escort", "Military Minelayer", "Military Transporter"]
	
	for object in objectcluster:
		if object.find('IsStatic') != None:
			if object.find('IsStatic').text == 'true': #Is a station, ignore it
				return False
		
		for block in object.find('CubeBlocks'):
			attrib = FindAttrib(block)
			if attrib == "MyObjectBuilder_Beacon": #Stop on first beacon, NPC ships only every have one beacon
				if block.find('CustomName') != None: #If the beacon doesn't have a custom name
					if block.find('CustomName').text != None: #If it has a blank custom name, blank custom names have a node, but it doens't have a text value
						if (block.find('CustomName').text in namestofind) and object.find('DampenersEnabled') != None: #If the beacon name matches one in the list and InertialDampners are off (it's adrift, no one's taken it)
							if object.find('DampenersEnabled').text == 'false':
								return True #Sounds like an NPC
			
	
	#Made it out here, musn't be an NPC
	return False


#Function to decide if it's safe to respawn an asteroid, based on the proximity of players and cubegrids
def CanRespawnAsteroid(avoidcoordslist, entpos, saferange):
	
	#Numbers are currently in strings. Convert to floats
	entpos["x"] = float(entpos["x"])
	entpos["y"] = float(entpos["y"])
	entpos["z"] = float(entpos["z"])
	
	for c in avoidcoordslist:
		c["x"] = float(c["x"])
		c["y"] = float(c["y"])
		c["z"] = float(c["z"])
		dist = (abs(c["x"] - entpos["x"]) + abs(c["y"] - entpos["y"]) + abs(c["z"] - entpos["z"]))
		if dist < saferange: #If something is too close
			return False #Do not respawn. God help you if you trap some poor bastard in an asteroid
			
	#Made it outside, must be good
	return True
	
#Function to save a backup of an asteroid / asteroid moon
#With asteroids, we work with the Voxel files. Simple backups and overwrites
#Graps if from the sectorobject's "FileName" node, so will always have the .vox extension included
def SaveAsteroid(asteroidname):
	XPrint("Saving snapshot of asteroid: " + asteroidname)

	#First, make sure the snapshot folder exists
	if not os.path.isdir(asteroidsnapshotdir):
		#and make it if it doesn't
		os.makedirs(asteroidsnapshotdir)
	
	#Do the copy
	if not args.whatif == True:
		shutil.copyfile(args.save_path + asteroidname, asteroidsnapshotdir + asteroidname)
		
#Function to do the oposite, copy the contents of the snapshot back into the current voxel file
#Once again, fields from the filename node so will have .vox on the end
def RestoreAsteroid(asteroidname):
	if os.path.isfile(asteroidsnapshotdir + asteroidname): #Does a backup for that asteroid exist?
		XPrint("Respawning asteroid: " + asteroidname)
		if not args.whatif == True:
			shutil.copyfile(asteroidsnapshotdir + asteroidname, savedir + asteroidname)
	else: #If it doesn't exist
		XPrint("Unable to respawn asteroid, no backup exists: " + asteroidname)
	
	
#########################################
### Main ################################
#########################################

#Load up argparse
argparser = argparse.ArgumentParser(description="Utility for performing maintenance & cleanup on SE save files.")
argparser.add_argument('save_path', nargs='?', help='Path to the share folder.', default='') #? used to compress into single item (not list) and will accept it if it's missing
argparser.add_argument('--skip-backup', '-B', help='Skip backup up the save files.', default=False, action='store_true')
argparser.add_argument('--big-backup', '-b', help='Save the backups as their own files with timestamps. Can make save folder huge after a few backups.', default=False, action='store_true')
argparser.add_argument('--cleanup-items', '-i', help="Clean up free floating objects like ores and components. Doesn't do corpses, they are more complicated.", default=False, action='store_true')
argparser.add_argument('--prune-players', '-p', help="Removes old entries in the player list. Considered old if they don't own any blocks and either don't belong to a faction or IsDead is true. WARNING: Running this on a single-player save will force you to respawn.", default=False, action='store_true')
argparser.add_argument('--prune-factions', '-f', help="Remove empty factions", default=False, action='store_true')
argparser.add_argument('--whatif', '-w', help="For debugging, won't do any backups and won't save changes.", default=False, action='store_true')
argparser.add_argument('--disable-factories', '-d', help='To save on wasted CPU cycles, turn off factories. Soft turns off idle assemblers and empty refineries. Hard turns off assemblers and refineries regardless.',
	default="",metavar="soft / hard", choices=['soft', 'hard'], nargs=1)
argparser.add_argument('--stop-movement', '-m', help="Stops all CubeGrid linear and angular velocity, stopping them still. WARNING: This will affect civilian ships as well, may lead to a buildup of civilian ships as they rely on inertia to leave the sector.", default=False, action='store_true')
argparser.add_argument('--remove-npc-ships', '-n', help='Removes any ship with inertial dampners turned off and have a beacon named Private Sail, Business Shipment, Commercial Freighter, Mining Carriage / Transport / Hauler and Military Escort / Minelayer / Transporter. Is a rough match but the option is there.', default=False, action='store_true')
argparser.add_argument('--ignore-joint', '-I', help="At current, the utility won't remove anything with a joint on it (e.g. motor). This restriction can be ignored but use with caution as it may leave 1-ended joints.", default=False, action='store_true')
argparser.add_argument('--full-cleanup', '-F', help="A complete cleanup. Cleans Factions, Players, Items and all unpowered Objects. Also soft-disables factories and stops movement", default=False, action='store_true')
argparser.add_argument('--save-asteroids', '-s', help="Saves a copy of all asteroids as they are", default=False, action='store_true')
argparser.add_argument('--respawn-asteroids', '-r', help="If there's nothing close to the asteroids, restores them to their original state from a backup", default=False, action='store_true')
argparser.add_argument('--cleanup-unpowered', '-u', help="When setting up a cleanup, removes objects without reactors or batteries or with unfueled reactors or dead batteries. By default, doesn't count solar panels as power", default=False, action='store_true')
argparser.add_argument('--cleanup-include-solar', '-S', help="Normally solar panels are excluded because its impossible to confirm with certainty that it's powered. Using this switch forces them to be included in the power check."
	, default=False, action='store_true')
argparser.add_argument('--cleanup-missing-attrib', '-c', help="Removes objects that are missing cubes with the given attribute, except those that have cubes that match --cleanup-missing-subtype. A list of attributes can be found on the wiki.", nargs="*", default=[])
argparser.add_argument('--cleanup-missing-subtype', '-C', help="Removes objects that are missing cubes with the given subtype, except those that have cubes that match --cleanup-missing-attrib. A list of subtypes can be found on the wiki.", nargs="*", default=[])
argparser.add_argument('--remove-refinery-queue', '-Q', help="As of SE 01.043, the refinery queue self-replicates and can easily get out of control and cause serious lag. This removes the 'queue' node from refineries which doesn't seem to really do anything.", default=False, action='store_true')

	
args = argparser.parse_args()

print("")
#print(args)
#print("")

#Definition for a full cleanup
if args.full_cleanup == True:
	args.cleanup_unpowered = True
	args.cleanup_items = True
	args.prune_players = True
	args.prune_factions = True
	args.stop_movement = True
	args.disable_factories = "soft"
	args.remove_refinery_queue = True

#Check to see if an action has been specified
simpleusagemsg = """
To quickly use this utility in Windows;
- Hold the Windows keyboard key and press R
	A window saying Open or Run will appear
- Type in "cmd" and press Enter
	A black window with white writing will appear
- Drag & drop SEMU into the window, hit Space and then type "-h" and hit enter
	This is the list of available options for SEMU
- Drag & drop SEMU into the window again
- Press space, then drag & drop the save folder to clean into the window
- Press space, then enter the commands you want to use
e.g. Semu.exe C:\save\path\ --full-cleanup

For instructions on how to make shortcuts & scripts
for frequent cleanups, check out the wiki on the SEMU site;
https://sourceforge.net/projects/semaintenanceutility/
"""

if (args.cleanup_unpowered == False) and (len(args.cleanup_missing_attrib) == 0) and (len(args.cleanup_missing_subtype) == 0) and (args.prune_factions == False) and (args.cleanup_items == False) and (args.prune_players == False) and (args.disable_factories == "") and (args.stop_movement == False) and (args.remove_npc_ships == False) and (args.save_asteroids == False) and (args.respawn_asteroids == False) and (args.remove_refinery_queue == False):
	print("Error: no actions given.")
	print(simpleusagemsg)
	input("Press the ENTER key to exit.")
	sys.exit()
	
if (args.save_path == ''):
	print("Error: No save path given.")
	print(simpleusagemsg)
	input("Press the ENTER key to exit.")
	sys.exit()
	
		

#Ok, we're good. Get the log ready
logfilename = OpenLog()

#Replace all "\" with "/" and add an "/" on the end if it's missing
args.save_path = args.save_path.replace("\\","/")
if args.save_path[-1:] != "/":
	args.save_path = args.save_path + "/"
	
### Save some in-built vars ###
savedir = args.save_path
asteroidsnapshotdir = savedir + "semu-asteroid-snapshots/"
entitysnapshotdir = savedir + "semu-entity-snapshots/"
asteroidspawnrange = 600 #Nothing can be within this many units of an asteroid for it to safely respawn
moonspawnrange = 200 #Nothing can be within this many units of an asteroid moon for it to safely respawn

#Set up names
smallsavefilename = "Sandbox.sbc"
largesavefilename = "SANDBOX_0_0_0_.sbs"
	
smallsavefilepath = savedir + smallsavefilename
largesavefilepath = savedir + largesavefilename

#Attempt to find the save folder
if not os.path.isdir(savedir):
	XPrint("ERROR: Unable to load save folder.")
	XPrint(savedir)
	sys.exit()

#Check for save files
if not os.path.isfile(smallsavefilepath):
	XPrint("ERROR: Unable to find small save: %s"%smallsavefilename)
	sys.exit()
if not os.path.isfile(largesavefilepath):
	XPrint("ERROR: Unable to find small save: %s"%largesavefilename)
	sys.exit()

#Save backups
if args.skip_backup == False and args.whatif == False:
	XPrint("Saving backups...")
	if args.big_backup == True:
		timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
		smallbackupname = "%s.%s.backup"%(smallsavefilepath, timestamp)
		largebackupname = "%s.%s.backup"%(largesavefilepath, timestamp)
	else:
		smallbackupname = smallsavefilepath + ".backup"
		largebackupname = largesavefilepath + ".backup"
	
	#print "Saving: " + smallbackupname
	XPrint("Saving smallsave backup...")
	shutil.copyfile(smallsavefilepath, smallbackupname)
	#print "Saving: " + largebackupname
	XPrint("Saving largesave backup...")
	shutil.copyfile(largesavefilepath, largebackupname)

#Load saves
XPrint("Loading %s..."%smallsavefilename)
xmlsmallsavetree = ET.parse(smallsavefilepath)
xmlsmallsave = xmlsmallsavetree.getroot()

XPrint("Loading %s file..."%largesavefilename)
xmllargesavetree = ET.parse(largesavefilepath)
xmllargesave = xmllargesavetree.getroot()

XPrint("Getting Started...")

#Try to find the Sector Objects node
if xmllargesave.find('SectorObjects') == None:
	XPrint("Error: Unable to locate SectorObjects node!")
	sys.exit()

sectorobjects = xmllargesave.find('SectorObjects')

#Init the ownership table
owningplayers = []

#Big loop through entity list
XPrint("===Beginning SectorObject check...===")

#Rewrote to be more dynamic and to allow treating multiple entites / objects as one (motor joins). Lets call these 'object clusters'
#Lets always treat things as a cluster. Even if it's a cluster of 1. Will need to modify functions to match
#Removing clusters this way should be safe. The big concern was that if I were to start removing mid-loop, not only
#	would my end point be changed, but so would the current position and objects would be skipped. This way,
#	as long as touching any part of the cluster reveals the entire cluster, it will never remove backwards, always forwards
i = 0
while i < len(sectorobjects):
	#---If removing an entity, DO NOT i++ !!!---
	object = sectorobjects[i]
	objectclass = FindAttrib(object)
	
	#print("Checking object")
	#print(objectclass)
	
	#---Process non-cubegrid stuff first---
	
	#Remove free floating objects
	if objectclass == "MyObjectBuilder_FloatingObject" and args.cleanup_items == True:
		#XPrint("Removing free-floating object: ",  object.find('EntityId').text)
		XPrint("Removing free-floating object: ", object.find('EntityId').text, " ", GetFloatingItemName(object))
		sectorobjects.remove(object)
		continue #Next object
	
	#---CubeGrid Stuff---
	#if IsCubeGrid(object) == True:
	if objectclass == "MyObjectBuilder_CubeGrid":
		
		#ROTORS ARE JOINED BY PROXIMITY WHEN THE SERVER STARTS
		#UNTIL YOU FIGURE OUT HOW TO CALCULATE THIS IN THE SAVE, JUST USE A SINGLE CLUSTER PER OBJECT
		# AND IGNORE PRUNING ALL OBJECTS THAT HAVE ROTORS ATTACHED TO THEM
		#objectcluster = MapObjectCluster(sectorobjects, object) #Generate the entity cluster map
		objectcluster = [object]
		
		#---Always process removal stuff before modify---
		#DO NOT REMOVE ANYTHING WITH A ROTOR OR STATOR OR PISTON unless the override is given, currently unable to map past joints
		
		#print(HasJoint(objectcluster))
		if HasJoint(objectcluster) == False or args.ignore_joint == True:
			#print("Checking object: " + objectcluster[0].find('EntityId').text + " " + objectclass)
			if args.remove_npc_ships == True and IsClusterAnNPC(objectcluster) == True:
				#print "Removing NPC entity: " + " ,".join(objectcluster)
				XPrint("! Removing NPC entity: ", object.find('EntityId').text, " ", FindObjectName(objectcluster) ) #Just until clusters get sorted
				for o in objectcluster:
					sectorobjects.remove(o)
				continue #Next sector object
			
			if args.cleanup_unpowered == True or len(args.cleanup_missing_attrib) > 0 or len(args.cleanup_missing_subtype) > 0 : #If its cleanup o'clock and it's a CubeGrid like a station or ship
				#print("Do I remove this?")
				if DoIRemoveThisCluster(objectcluster, args.cleanup_missing_attrib, args.cleanup_missing_subtype, args.cleanup_unpowered, args.cleanup_include_solar) == True:
					#print "Removing CubeGrid entites: " + " ,".join(objectcluster)
					XPrint("! Removing CubeGrid") #Just until clusters get sorted
					for o in objectcluster:
						sectorobjects.remove(o)
					continue #Next sector object, we're removing this one anyway
				else:
					XPrint("  Entity passed check")
					#print("Object passes inspection: " + object.find('EntityId').text) #Just until clusters get sorted
		
		#Remove this Else when you've got joints sussed out
		else:
			pass
			#XPrint("Skipping object that has a joint: " + objectcluster[0].find('EntityId').text)
			
		
		#End of If HasJoint
		
		#---After processing removal stuff, THEN do modify stuff---
		
		#Add to owner list
		for owner in GetClusterOwners(objectcluster):
			if not owner in owningplayers:
				owningplayers.append(owner)
		
		#Turn off factories
		#if args.disable_factories != '':
		if len(args.disable_factories) > 0:
			DisableFactories(objectcluster, args.disable_factories[0])
		
		#Remove refinery queues
		if args.remove_refinery_queue == True:
			RemoveRefineryQueue(objectcluster)
		
		#Stop movement
		if args.stop_movement == True:
			KillClusterInertia(objectcluster)
		
	#end CubeGrid if
		
	#Made it to the end without removing object, go to the next item
	i = i + 1
	
#End SectorObjects loop

#After cleanup, should be good to save snapshots
#Asteroids
if args.save_asteroids == True:
	XPrint("===Beginning asteroid snapshot...===")
	for object in sectorobjects:
		if FindAttrib(object) == "MyObjectBuilder_VoxelMap":
			#Save a copy of this entity to a backup
			SaveAsteroid(object.find('Filename').text) #Don't worry about Print, SaveAsteroid will do that
#End asteroid saving

#Sector objects have now been cleaned up, lets thing about respawning
#Asteroids
if args.respawn_asteroids == True:
	XPrint("===Beginning asteroid respawn...===")
	
	#For efficiency, generate a list of what entites are where
	avoidents = []
	for object in sectorobjects:
		if FindAttrib(object) == "MyObjectBuilder_Character" or FindAttrib(object) == "MyObjectBuilder_CubeGrid": #Only do checks for CubeGrids and players. Who cares about floating items or other asteroids.
			avoidents.append(object.find('PositionAndOrientation').find('Position').attrib) #Add the XYZ dict to the list
			
	
	#Now, loop through the asteroids and check if they should be respawned
	for object in sectorobjects:
		if FindAttrib(object) == "MyObjectBuilder_VoxelMap":
			
			#Is it a moon or a large asteroid?
			ismoon = ("moon" in object.find('Filename').text)
			range = 0
			
			if ismoon == True: range = moonspawnrange
			if ismoon == False: range = asteroidspawnrange
			
			if CanRespawnAsteroid(avoidents, object.find('PositionAndOrientation').find('Position').attrib, range):
				RestoreAsteroid(object.find('Filename').text)
				
			else:
				XPrint("Can't respawn asteroid, something is too close: " + object.find('Filename').text)
#End asteroid respawning
	
#Begin player check. Must be after object check
if args.prune_players == True:
	XPrint("===Beginning player check...===")
	
	playerlist = xmlsmallsave.find('AllPlayers')
	playerIDtoremove = []
	
	#This'll be slightly different because there's 2 player lists
	"""
	for player in playerlist:
		playerID = player.find('PlayerId').text
		if (not playerID in owningplayers) == True and (player.find('IsDead').text == 'true' or FindPlayerFaction(xmlsmallsave.find('Factions').find('Factions'), playerID) == None): #Doesn't own anything AND (isDead = True OR not in a faction)
			try: #Error handling for unicode names
				XPrint("Marking player for removal: %s, %s"%(player.find('Name').text, playerID))
			except:
				XPrint("Marking player for removal: %s, %s"%("<unicode name>", playerID))
			
			playerIDtoremove.append(playerID)
	"""
	for player in playerlist:
		playerID = player.find('PlayerId').text
		XPrint("Checking player entry: ", playerID, " ", player.find('Name').text)
		ownsstuff = playerID in owningplayers
		isdead = player.find('IsDead').text == 'true'
		inafaction = FindPlayerFaction(xmlsmallsave.find('Factions').find('Factions'), playerID) != None
		
		XPrint("Owns stuff   : ", ownsstuff)
		XPrint("Is alive     : ", not isdead)
		XPrint("Is in faction: ", inafaction)
		
		if (not ownsstuff) == True and (isdead or not inafaction): #Doesn't own anything AND (isDead = True OR not in a faction)
			XPrint("Marking player for removal: ", player.find('Name').text, ", ", playerID)
			playerIDtoremove.append(playerID)
	#End player list loop
	
	#Remove from relevant lists
	if len(playerIDtoremove) > 0: #If there's things to do
		XPrint("===Removing marked players...===")
		
		#AllPlayers section
		apltoremove = []
		for i in range(0, len(playerlist)):
			if playerlist[i].find('PlayerId').text in playerIDtoremove:
				apltoremove.append(i)
				XPrint("Removing ", playerlist[i].find('PlayerId').text, " from All Players list")
		apltoremove.reverse()
		for i in apltoremove:
			playerlist.remove(playerlist[i])
			
		#Players section. Yes, there's a second one
		pltoremove = []
		pllist = xmlsmallsave.find('Players')[0]
		for i in range(0, len(pllist)):
			if pllist[i].find('Value').find('PlayerId') in playerIDtoremove:
				XPrint("Removing ", pllist[i].find('Value').find('PlayerId') , " from Players list")
				pltoremove.append(i)
		pltoremove.reverse()
		for i in pltoremove:
			pllist.remove(pllist[i])
			
		#Factions
		#Loop through members of each faction.
		for faction in xmlsmallsave.find('Factions').find('Factions'):
			factionId = faction.find('FactionId').text
			memberlist = faction.find('Members')
			joinrequests = faction.find('JoinRequests')
			membertoremove = []
			
			
			#Cleanup Members
			for i in range(0, len(memberlist)):
				if memberlist[i].find('PlayerId').text in playerIDtoremove:
					XPrint("Removing ", memberlist[i].find('PlayerId').text, " from faction ", factionId, " ", faction.find('Name').text)
					membertoremove.append(i)
			membertoremove.reverse()
			for i in membertoremove:
				memberlist.remove(memberlist[i])
			
			#Cleanup Join Requests
			requesttoremove = []
			for i in range(0, len(joinrequests)):
				if joinrequests[i].find('PlayerId').text in playerIDtoremove:
					XPrint("Removing ", joinrequests[i].find('PlayerId').text, " from faction request list ", factionId, " ", faction.find('Name').text)
					requesttoremove.append(i)
			requesttoremove.reverse()
			for i in requesttoremove:
				joinrequests.remove(joinrequests[i])
		
		#Factions Players, yep another second one
		factionplayers = xmlsmallsave.find('Factions').find('Players')[0]
		fptoremove = []
		for i in range(0, len(factionplayers)):
			if factionplayers[i].find('Key').text in playerIDtoremove:
				XPrint("Removing ", factionplayers[i].find('Key').text, "from faction player list")
				fptoremove.append(i)
		fptoremove.reverse()
		for i in fptoremove:
			factionplayers.remove(factionplayers[i])
#End player pruning
	

#Begin checking factions. Must be after object check and player check
if args.prune_factions == True:
	XPrint("===Beginning faction check...===")
	
	factionIDtoremove = []
	
	if xmlsmallsave.find('Factions') == None:
		XPrint("Error: Unable to location the Factions node in save!")
		sys.exit()
	
	#Find and mark down factions to be removed
	factionlist = xmlsmallsave.find('Factions').find('Factions')
	factionlisttoremove = []
	for i in range(0, len(factionlist)):
		if len(factionlist[i].find('Members')) == 0: #Has no members
			XPrint("Marking faction for removal, no members: ", factionlist[i].find('Name').text, ", ", factionlist[i].find('FactionId').text)
				
			factionIDtoremove.append(factionlist[i].find('FactionId').text)
			factionlisttoremove.append(i)
	
	XPrint("===Removing marked factions...===")
	
	#Remove from main faction table
	factionlisttoremove.reverse()
	for i in factionlisttoremove:
		factionlist.remove(factionlist[i])
	
	#Skip the FactionPlayer table. Will only remove factions that have no players, so it should never even be present in the FactionPlayers list
	
	#Remove from Relations table
	factionrelations = xmlsmallsave.find('Factions').find('Relations')
	factionrelationstoremove = []
	for i in range(0, len(factionrelations)):
		if (factionrelations[i].find('FactionId1').text in factionIDtoremove) or (factionrelations[i].find('FactionId2').text in factionIDtoremove):
			factionrelationstoremove.append(i)
	factionrelationstoremove.reverse()
	for i in factionrelationstoremove:
		factionrelations.remove(factionrelations[i])
	
	#Clean from FactionRequests
	#2 kinds, either an entire entry for the faction or another entry referring to the faction
	factionrequests = xmlsmallsave.find('Factions').find('Requests')
	requestbodytoremove = []
	for i in range(0, len(factionrequests)):
		#First, is this entry about a faction to be removed
		if factionrequests[i].find('FactionId').text in factionIDtoremove:
			requestbodytoremove.append(i)
			continue #Go to the next entry, don't bother about the individual requests
		
		#Second, loop through the requests that've been sent by this faction
		factionsubrequests = factionrequests[i].find('FactionRequests')
		subrequesttoremove = []
		for i in range(0, len(factionsubrequests)):
			if factionsubrequests[i].text in factionIDtoremove:
				subrequesttoremove.append(i)
		subrequesttoremove.reverse()
		for i in subrequesttoremove:
			factionsubrequests.remove(factionsubrequests[i])
	
	requestbodytoremove.reverse()
	for i in requestbodytoremove:
		factionrequests.remove(factionrequests[i])
	
	
#Ok, that should be all the checks, lets save it
if args.whatif == False:
	XPrint("===Saving changes...===")
	XPrint("Saving largesave...")
	xmllargesave.attrib["xmlns:xsd"]="http://www.w3.org/2001/XMLSchema"
	xmllargesavetree.write(largesavefilepath)

	XPrint("Saving smallsave...")
	#Space Engineers freaks the fuck out if the top of the XML in the sbc file isn't juuuuuuust right
	xmlsmallsave.attrib["xmlns:xsd"]="http://www.w3.org/2001/XMLSchema"
	xmlsmallsavetree.write(smallsavefilepath)
else:
	XPrint("===Script complete. WhatIf was used, no action has been taken.===")
