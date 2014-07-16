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
	
"""

import xml.etree.ElementTree as ET #Used to read the SE save files
import argparse #Used for CLI arguments
#import os #For file system checks
import shutil #For copying files to backups
import datetime #For backup naming

#########################################
### Functions ###########################
#########################################

#Function to check if the object should be removed
def DoIRemoveThisGrid(objnode, mode):
	hasreactor = True
	hasbeacon = False
	haspower = False
	
	for block in objnode.find('CubeBlocks'):
		if len(block.attrib.values()) > 0: #If it has an attribute
			if block.attrib.values()[0] == "MyObjectBuilder_Reactor":
				#Ok, it's a reactor.
				hasreactor = True
				
				#Is it enabled and has power?
				fuel = False
				
				#Loop through Inventory
				inventory = block.find('Inventory').find('Items')
				
				
				#As long as there's something in the inventory, you can only put fuel in a reactor, so it has fuel
				if block.find('Enabled').text == "true" and len(inventory) > 0:
					haspower = True
			
			if block.attrib.values()[0] == "MyObjectBuilder_Beacon":
				hasbeacon = True
		
	#End of block loop
	if mode == "junk" and hasreactor == False:
		return True #No reactor on here, kill it
	
	if mode == "dead" and haspower == False:
		return True #KILL IT
	
	if mode == "beacon" and haspower != True and hasbeacon != True:
		return True #No power, no beacon, kill it
	
	#Made it here, musn't be kill worthy
	return False
		
#Function to get a list of players that own at least a part of this ship
def GetOwners(objnode):
	shareholders = []
	
	for obj in objnode.find('CubeBlocks'):
		if obj.find('Owner') != None: #If there is an Owner tag on this block
			if obj.find('Owner').text not in shareholders: #If this owner isn't currently recorded
				shareholders.append(obj.find('Owner').text) #Add it to the list
				
	return shareholders

#Function to get members of a faction
def GetFactionMembers(factionNode):
	members = []
	
	for member in factionNode.find('Members'):
		members.append(member.find('PlayerId').text)
	
	return members
	
#Function to clean up factions
#Empty factions are easy. Look through the xml, if the faction has no players, nuke it
#Bum factions are trickier. Look through all of the can-own objects in the world
#Take a list of what playerID owns which blocks
#If none of the members of a faction have ownership of any blocks, disband it
#You'll also need to compensate for objects removed during cleanup


#########################################
### Main ################################
#########################################

#Load up argparse
argparser = argparse.ArgumentParser(description="Utility for performing maintenance & cleanup on SE save files")
argparser.add_argument('save_path', nargs=1, help='path to the share folder')
#argparser.add_argument('--skip-backup', '-B', help='skip backup up the sbs file', dest='skip_backup', action='store_true')
argparser.add_argument('--skip-backup', '-B', help='skip backup up the save files', default=False, action='store_true')
argparser.add_argument('--big-backup', '-b', help='save the backups as their own files with timestamps. Can make save folder huge after a few backups', default=False, action='store_true')
argparser.add_argument('--cleanup-objects', '-c', 
	help="clean up objects in the world. Junk mode removes everything without a reactor, alive or not. Dead mode removes anything without an enabled & fueled reactor. Beacon mode removes anything that doesn't have a beacon, or an unfinished beacon, and doesn't have an enabled & fueled reactor (inspired by borg8401)",
	choices=['junk', 'dead', 'beacon'], metavar="MODE", default="")
argparser.add_argument('--cleanup-items', '-C', help="clean up free floating objects like ores and components. Doesn't do corpses, they are more complicated", default=False, action='store_true')
#Researching a way to remove inactive factions
argparser.add_argument('--prune-players', '-p', help="removes old entries in the player list. Considered old if they don't own any blocks.", default=False, action='store_true')
argparser.add_argument('--prune-factions', '-f', help="remove empty factions and factions that don't own anything", default=False, action='store_true')
argparser.add_argument('--whatif', '-w', help="for debugging, won't do any backups and won't save changes", default=False, action='store_true')
	
args = argparser.parse_args()

print ""

#Check to see if an action has been specified
if args.cleanup_objects == "" and args.prune_factions == False and args.cleanup_items == False and args.prune_players == False:
	print "Error: No action specified"
	argparser.print_help()
	exit()

#Attempt to load save file
args.save_path[0] = args.save_path[0].replace("\\","/")
if args.save_path[0] != "/": #Add on the trailing / if it's missing
	args.save_path[0] = args.save_path[0] + "/"

smallsavefilename = "Sandbox.sbc"
largesavefilename = "SANDBOX_0_0_0_.sbs"
	
smallsavefilepath = args.save_path[0] + smallsavefilename
largesavefilepath = args.save_path[0] + largesavefilename

#Save backups
if args.skip_backup == False and args.whatif == False:
	print "Saving backups..."
	if args.big_backup == True:
		timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
		smallbackupname = smallsavefilepath + ".backup" + timestamp
		largebackupname = largesavefilepath + ".backup" + timestamp
	else:
		smallbackupname = smallsavefilepath + ".backup"
		largebackupname = largesavefilepath + ".backup"
	
	print "Saving: " + smallbackupname
	shutil.copyfile(smallsavefilepath, smallbackupname)
	print "Saving: " + largebackupname
	shutil.copyfile(largesavefilepath, largebackupname)

print "Loading %s..."%smallsavefilename
xmlsmallsavetree = ET.parse(smallsavefilepath)
xmlsmallsave = xmlsmallsavetree.getroot()

print "Loading %s file..."%largesavefilename
xmllargesavetree = ET.parse(largesavefilepath)
xmllargesave = xmllargesavetree.getroot()

print "Getting Started..."

#Try to find the Sector Objects node
if xmllargesave.find('SectorObjects') == None:
	print "Error: Unable to locate SectorObjects node!"
	exit()

	
sectorobjects = xmllargesave.find('SectorObjects')
	
#Init Lists
objectstoremove = []
owningplayers = []

print "Beginning check..."
#Big loop through entity list
for i in range(0, len(sectorobjects)):
	object = sectorobjects[i]
	objectclass = object.attrib.values()[0]
	
	#Removing corpses
	#Corpses are more complicated, it looks like they're closely tied into other things. More research needed
	#if objectclass == "MyObjectBuilder_Character" and args.cleanup_items == True:
	#	if object.find('Health').text == None:
	#		continue #Character is at full health, do nothing
	#	if float(object.find('Health').text) <= 0: #If his health is either 0 or below
	#		print "Marking corpse for removal: ", object.find('EntityId').text
	#		objectstoremove.append(i)
	#		continue #Next object
	
	#Removing free floating items
	if objectclass == "MyObjectBuilder_FloatingObject" and args.cleanup_items == True:
		print "Marking free-floating object for removal: ",  object.find('EntityId').text
		objectstoremove.append(i)
		continue #Next object
	
	#Only do stuff to CubeGrids, otherwise, its an asteroid or an item or a player. 
	#Either way, something that you shouldn't be removing
	#print object.attrib.values()[0]
	if object.attrib.values()[0] != "MyObjectBuilder_CubeGrid":
		continue #Skip, onto the next
	
	if args.cleanup_objects != "" and objectclass == "MyObjectBuilder_CubeGrid" : #If its cleanup o'clock and it's a CubeGrid like a station or ship
		if DoIRemoveThisGrid(object, args.cleanup_objects) == True:
			#objectstoremove.append(i)
			print "Marking object for removal: ", object.find('EntityId').text
			#sectorobjects.remove(object) #Remove this object
			objectstoremove.append(i)
			continue #Don't do any more checks. This entity is being destroyed and won't have any further baring on calculations
	
	#if args.prune_factions == True: #If a cleanup of factions will be performed
	#Changed it, make the list anyway. If an exception occurs, chances are that its an unownable block
	try:
		owningplayers.extend(GetOwners(object))
		break
	except:
		pass #Do nothing if it shits the bed
	
#End object loop

#Remove marked objects
if args.cleanup_objects != "":
	print "Removing marked objects..."
	objectstoremove.reverse()
	for i in objectstoremove:
		sectorobjects.remove(sectorobjects[i])

		
#Begin player check. Must be after object check
if args.prune_players == True:
	print "Beginning player check..."
	
	playerlist = xmlsmallsave.find('AllPlayers')
	playerIDtoremove = []
	
	#This'll be slightly different because there's 2 player lists
	#First, get a list of players
	for player in playerlist:
		playerID = player.find('PlayerId').text
		if (not playerID in owningplayers) == True and (player.find('IsDead').text == 'true'): #If they don't own anything and this player entity is dead
			print "Marking player for removal: %s, %s"%(player.find('Name').text, playerID)
			playerIDtoremove.append(playerID)
	
	#Remove from relevant lists
	print "Removing marked players..."
	
	#AllPlayers section
	apltoremove = []
	for i in range(0, len(playerlist)):
		if playerlist[i].find('PlayerId').text in playerIDtoremove:
			apltoremove.append(i)
			print "Removing %s from All Players list"%playerlist[i].find('PlayerId').text
	apltoremove.reverse()
	for i in apltoremove:
		playerlist.remove(playerlist[i])
		
	#Players section. Yes, there's a second one
	pltoremove = []
	pllist = xmlsmallsave.find('Players')[0]
	for i in range(0, len(pllist)):
		if pllist[i].find('Value').find('PlayerId') in playerIDtoremove:
			print "Removing %s from Players list"%pllist[i].find('Value').find('PlayerId')
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
				print "Removing %s from faction %s"%(memberlist[i].find('PlayerId').text, factionId)
				membertoremove.append(i)
		membertoremove.reverse()
		for i in membertoremove:
			memberlist.remove(memberlist[i])
		
		#Cleanup Join Requests
		requesttoremove = []
		for i in range(0, len(joinrequests)):
			if joinrequests[i].find('PlayerId').text in playerIDtoremove:
				print "Removing %s from faction request list %s"%(joinrequests[i].find('PlayerId').text, factionId)
				requesttoremove.append(i)
		requesttoremove.reverse()
		for i in requesttoremove:
			joinrequests.remove(joinrequests[i])
	
	#Factions Players, yep another second one
	factionplayers = xmlsmallsave.find('Factions').find('Players')[0]
	fptoremove = []
	for i in range(0, len(factionplayers)):
		if factionplayers[i].find('Key').text in playerIDtoremove:
			print "Removing %s from faction player list"%factionplayers[i].find('Key').text
			fptoremove.append(i)
	fptoremove.reverse()
	for i in fptoremove:
		factionplayers.remove(factionplayers[i])
#End player pruning
	
		
#Begin checking factions. Must be after object check and player check
if args.prune_factions == True:
	print "Beginning faction check..."
	#print "Owning Players:"
	#print owningplayers	
	
	"""
	
	factionstoremove = []
	
	if xmlsmallsave.find('Factions') == None:
		print "Error: Unable to location the Factions node in save!"
		exit()
	
	factionlist = xmlsmallsave.find('Factions').find('Factions')
	for i in range(0,len(factionlist)):
		faction = factionlist[i]
		if len(faction.find('Members')) == 0:
			#print "Removing faction, no members: " + faction.find('Name').text
			print "Marking faction for removal, no members: " + faction.find('Name').text
			#factionlist.remove(faction) #Remove the faction
			factionstoremove.append(i)
			continue #Move onto next faction
	
		hasshareholder = False
		members = GetFactionMembers(faction)
		for member in members:
			#print (member in owningplayers)
			if member in owningplayers: #If this member is in the list of players that own something
				hasshareholder = True
		
		if hasshareholder == False: #Too bad son, you're a broke-ass faction and I'mma delete you
			#print "Removing faction, owns nothing: " + faction.find('Name').text
			print "Marking faction for removal, owns nothing: " + faction.find('Name').text
			factionstoremove.append(i)
			#factionlist.remove(faction)
			continue #Check the next faction
			
	#End faction loop
	
	#Remove factions on list
	print "Removing marked factions..."
	factionstoremove.reverse()
	for i in factionstoremove:
		factionlist.remove(factionlist[i])
	"""
	
	factionIDtoremove = []
	
	if xmlsmallsave.find('Factions') == None:
		print "Error: Unable to location the Factions node in save!"
		exit()
	
	#Find and mark down factions to be removed
	factionlist = xmlsmallsave.find('Factions').find('Factions')
	factionlisttoremove = []
	for i in range(0, len(factionlist)):
		if len(factionlist[i].find('Members')) == 0: #Has no members
			print "Marking faction for removal, no members: %s - %s"%(factionlist[i].find('Name').text, factionlist[i].find('FactionId').text)
			factionIDtoremove.append(factionlist[i].find('FactionId').text)
			factionlisttoremove.append(i)
	
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
	print "Saving changes..."
	xmllargesavetree.write(largesavefilepath)

	#Space Engineers freaks the fuck out if the top of the XML in the sbc file isn't juuuuuuust right
	smallsavetowrite = ET.tostring(xmlsmallsave, method="xml")
	#Replace the first line with that special tag. Couldn't figure out how to get elementtree to do it for me
	smallsavetowrite = """<?xml version="1.0"?>\n<MyObjectBuilder_Checkpoint xmlns:xsd="http://www.w3.org/2001/XMLSchema" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">""" + smallsavetowrite[smallsavetowrite.find("\n"):] 
	#print smallsavetowrite[:100]
	f = open(smallsavefilepath, 'w')
	f.write(smallsavetowrite)
	f.close()
else:
	print "Script complete. WhatIf was used, no action has been taken."


