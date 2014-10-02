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

 v1.3.7
 - Added function to remove Spotlights. Only standard, might not work with Steam Workshop spotlights


"""

import xml.etree.ElementTree as ET #Used to read the SE save files
import argparse #Used for CLI arguments
import os #For file system checks & snapshot file working
import shutil #For copying files to backups
import datetime #For timestamps
import sys #for propper sys.exit()
import traceback #For some error handling verbosity
import logging

#########################################
### Functions ###########################
#########################################
logger = None


#Function to open the log
def OpenLog():
    logfoldername = "./semu_logs/"
    if not os.path.isdir(logfoldername):
        #and make it if it doesn't
        os.makedirs(logfoldername)

    filename = '{0}.log'.format(datetime.datetime.now().strftime("%Y%m%d_%H%M"))
    filename = os.path.join(logfoldername, filename)
    logging.basicConfig(filename=filename,
                        filemode='w',
                        format='%(asctime)s %(levelname)-8s %(message)s',
                        datefmt='%d.%m %H:%M',
                        level='INFO')

    # define a Handler which writes INFO messages or higher to the sys.stderr
    console = logging.StreamHandler()
    console.setLevel(logging.INFO)
    # set a format which is simpler for console use
    formatter = logging.Formatter('%(levelname)-8s %(message)s')
    # tell the handler to use this format
    console.setFormatter(formatter)
    # add the handler to the root logger
    logging.getLogger('').addHandler(console)


#Got shitty with crazy UTF characters breaking things. This function will attempt to make sense of it and return "<unicode>" if it breaks
def SafeString(input):
    if type(input) == str: #If it's a string, make sure it's not a unicode one
        try:
            return(input.encode('utf-8', 'ignore').decode('ascii')) #Try to recover from Unicode
        except Exception as err: #Fuck your shit Unicode, fuck it right in the mouth
            logger.error(err)
            return("<crazy unicode>") #Just add something, it failed
    else: #Must be something else. Either way, try to add it as a string
        return(str(input))


#Function to possibly find a CubeGrid's name. Search for the name(s) of Antennae and Beacons
def FindObjectName(objectcluster):
    foundnames = []

    for obj in objectcluster:
        if obj.find('DisplayName') is not None: #if a name has been specified under the Info tab
            if obj.find('DisplayName').text is not None: #Blank name, ignore it
                foundnames.append(SafeString(object.find('DisplayName').text))

        for block in obj.find('CubeBlocks'):
            attrib = FindAttrib(block)
            if attrib == "MyObjectBuilder_Beacon" or attrib == "MyObjectBuilder_RadioAntenna":
                #If it hasn't been given a custom name, then it's either called "Antenna" or "Beacon"
                if block.find('CustomName') is None:
                    if attrib == "MyObjectBuilder_Beacon":
                        foundnames.append("Beacon")
                    if attrib == "MyObjectBuilder_RadioAntenna":
                        foundnames.append("Antenna")
                else: #If it has a custom name
                    n = block.find('CustomName').text
                    if n is None: #If it has a blank name, use the default block names
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
    for obj in objectcluster:
        for cube in obj.find('CubeBlocks'):
            if cube.find('Queue') is not None and FindAttrib(cube) == "MyObjectBuilder_Refinery": #if there's a Queue node and it's a refinery, remove it
                logger.info("Removing refinery queue on entity: ", obj.find('EntityId').text)
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
        if node.find(idfieldname) is None: #Field not found in this node
            continue #Move on to the next node

        if node.find(idfieldname).text == idtosearchfor:
            return node

    #If it made it out of the loop, didn't find entity
    return None


#Function to get the name of a floating object
def GetFloatingItemName(objnode):
    #try:
        return "%s : %s" % (FindAttrib(objnode.find('Item').find('PhysicalContent')).replace("MyObjectBuilder_", ""), objnode.find('Item').find('PhysicalContent').find('SubtypeName').text) #type : name e.g. Ore : Iron
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
    for obj in objectcluster:
        for block in obj.find('CubeBlocks'):
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
    for obj in objectcluster:
        obj.find('LinearVelocity').attrib["x"] = "0"
        obj.find('LinearVelocity').attrib["z"] = "0"
        obj.find('LinearVelocity').attrib["y"] = "0"

        obj.find('AngularVelocity').attrib["x"] = "0"
        obj.find('AngularVelocity').attrib["y"] = "0"
        obj.find('AngularVelocity').attrib["z"] = "0"
#End KillClsterIntertia


#Function to decide whether to remove an object cluster
def DoIRemoveThisCluster(objectcluster, findattribs, findsubtypes, musthavepower=False, allowsolar=False):
    #Define checks
    haspower = False
    attribmatch = False
    subtypematch = False
    neededblock = False

    #Begin checking through object blocks
    for obj in objectcluster:
        logger.info("Checking entity:", obj.find("EntityId").text, " ", FindObjectName(objectcluster))
        for block in obj.find('CubeBlocks'):
            attrib = FindAttrib(block)
            logger.debug("'" + attrib + "'")
            subtype = block.find('SubtypeName').text

            #Power checks
            if attrib == "MyObjectBuilder_Reactor" and musthavepower: #If it's a reactor
                #Is it fueled? No matter what, if there's an item in a reactor, it's fueled. Possibility of fucking-up if SE starts allowing non-fuel into a reactor in future versions.
                if len(block.find('Inventory').find('Items')) > 0:
                    logger.info("- Found fueled reactor")
                    haspower = True #Has power, even if it's disabled
                else:
                    logger.info("- Found empty reactor")
            #End reactor check

            if attrib == "MyObjectBuilder_BatteryBlock" and musthavepower: #If it's a battery
                if block.find('CurrentStoredPower').text != '0':
                    logger.info("- Found charged battery")
                    haspower = True #Battery is juicing the juices, but may be disabled
                else:
                    logger.info("- Found dead battery")
            #End Battery check

            if attrib == "MyObjectBuilder_SolarPanel" and allowsolar and musthavepower: #If it's a battery and we're checking for power AND its been specified that we should include solar panels
                if block.find('Enabled').text == "true": #If by some miracle, they've managed to disable the panel
                    logger.info("- Found solar panel, including in power check")
                    haspower = True #Include it in the power check. I remind you that THIS IS NOT COUNTED BY DEFAULT.

            #Attrib & subtype checks
            if (subtype in findsubtypes):
                logger.info("- Found wanted subtype: " + subtype)
                neededblock = True #It has a block that we're after

            if (attrib in findattribs):
                logger.info("- Found wanted attribute: " + attrib)
                neededblock = True

        #End of block loop
    #End of cluster loop

    logger.debug("-DoIRemoveThisCluster-")
    logger.debug(haspower or not musthavepower)
    logger.debug(neededblock or (len(findattribs) == 0 and len(findsubtypes) == 0))

    if (haspower or not musthavepower) and (neededblock or (len(findattribs) == 0 and len(findsubtypes) == 0)): # If (haspower OR power not needed) AND (found needed block OR no blocks to search for)
        return False #Must be good, leave it alone
    else:
        return True #Blast it


#Function to loop through an object cluster and disable factories, hard or soft
def DisableFactories(objectcluster, mode):
    logger.debug("Checking for factories")
    logger.debug(objectcluster)
    logger.debug(mode)
    for obj in objectcluster:
        for block in obj.find('CubeBlocks'):
            attrib = FindAttrib(block)
            if attrib == "MyObjectBuilder_Refinery": #Is a refinery
                logger.debug("Found Refinery")
                if (mode == 'soft' and len(block.find('InputInventory').find('Items')) == 0) or mode == 'hard': #If the mode is 'soft' and there's nothing inside to be refined; or it's 'hard' mode to turn it off regardless
                    block.find('Enabled').text = "false" #Turn it off
                    logger.info("Turning off refinery on entity: ", obj.find('EntityId').text)

            if attrib == "MyObjectBuilder_Assembler": #Is an assembler
                logger.debug("Found Assembler")
                #Well aint that some shit, SE removes the 'Queue' node if there's nothing in the queue instead of leaving an empty node...
                if (mode == 'soft' and block.find('Queue') is None) or mode == 'hard': #If the mode is 'soft' and there's nothing in the queue; or it's 'hard' mode to turn it off regardless
                    block.find('Enabled').text = "false" #Turn it off
                    logger.info("Turning off assembler on entity: " + obj.find('EntityId').text)


#Function to get a list of players that own at least a part of this object cluster
def GetClusterOwners(objectcluster):
    shareholders = []

    for obj in objectcluster:
        for cube in obj.find('CubeBlocks'):
            if cube.find('Owner') is not None: #If there is an Owner tag on this block
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

    for obj in objectcluster:
        if obj.find('IsStatic') is not None:
            if obj.find('IsStatic').text == 'true': #Is a station, ignore it
                return False

        for block in obj.find('CubeBlocks'):
            attrib = FindAttrib(block)
            if attrib == "MyObjectBuilder_Beacon": #Stop on first beacon, NPC ships only every have one beacon
                if block.find('CustomName') is not None: #If the beacon doesn't have a custom name
                    if block.find('CustomName').text is not None: #If it has a blank custom name, blank custom names have a node, but it doens't have a text value
                        if (block.find('CustomName').text in namestofind) and obj.find('DampenersEnabled') is not None: #If the beacon name matches one in the list and InertialDampners are off (it's adrift, no one's taken it)
                            if obj.find('DampenersEnabled').text == 'false':
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
    logger.info("Saving snapshot of asteroid: " + asteroidname)

    #First, make sure the snapshot folder exists
    if not os.path.isdir(asteroidsnapshotdir):
        #and make it if it doesn't
        os.makedirs(asteroidsnapshotdir)

    #Do the copy
    if not args.whatif:
        shutil.copyfile(os.path.join(args.save_path, asteroidname), os.path.join(asteroidsnapshotdir, asteroidname))


#Function to loop through an object cluster and disable spotlights
#Written by RottieLover 30/08/2014
def DisableSpotLights(objectcluster):
    logger.debug("Checking for Spotlights")
    logger.debug(objectcluster)
    for obj in objectcluster:
        for block in obj.find('CubeBlocks'):
            attrib = FindAttrib(block)
            if attrib == "MyObjectBuilder_ReflectorLight": #Is a spotlight
                logger.debug ("Found Spotlight")
                block.find('Enabled').text = "false" #Turn it off
                logger.info("Turning off spotlight on entity: ", obj.find('EntityId').text)


#Function to do the oposite, copy the contents of the snapshot back into the current voxel file
#Once again, fields from the filename node so will have .vox on the end
def RestoreAsteroid(asteroidname):
    if os.path.isfile(os.path.join(asteroidsnapshotdir, asteroidname)): #Does a backup for that asteroid exist?
        logger.info("Respawning asteroid: " + asteroidname)
        if not args.whatif:
            shutil.copyfile(os.path.join(asteroidsnapshotdir,+ asteroidname), os.path.join(savedir, asteroidname))
    else: #If it doesn't exist
        logger.info("Unable to respawn asteroid, no backup exists: " + asteroidname)


#########################################
### Main ################################
#########################################
def main():
    global logger

    #Load up argparse
    argparser = argparse.ArgumentParser(description="Utility for performing maintenance & cleanup on SE save files.")
    argparser.add_argument('save_path', nargs='?', help='Path to the share folder.', default='') #? used to compress into single item (not list) and will accept it if it's missing
    argparser.add_argument('--skip-backup', '-B', help='Skip backup up the save files.', default=False, action='store_true')
    argparser.add_argument('--big-backup', '-b', help='Save the backups as their own files with timestamps. Can make save folder huge after a few backups.', default=False, action='store_true')
    argparser.add_argument('--cleanup-items', '-i', help="Clean up free floating objects like ores and components. Doesn't do corpses, they are more complicated.", default=False, action='store_true')
    argparser.add_argument('--prune-players', '-p', help="Removes old entries in the player list. Considered old if they don't own any blocks and either don't belong to a faction or IsDead is true. WARNING: Running this on a single-player save will force you to respawn.", default=False, action='store_true')
    argparser.add_argument('--prune-factions', '-f', help="Remove empty factions", default=False, action='store_true')
    argparser.add_argument('--whatif', '-w', help="For debugging, won't do any backups and won't save changes.", default=False, action='store_true')
    argparser.add_argument('--disable-factories', '-d', help='To save on wasted CPU cycles, turn off factories. Soft turns off idle assemblers and empty refineries. Hard turns off assemblers and refineries regardless.', default="", metavar="soft / hard", choices=['soft', 'hard'], nargs=1)
    argparser.add_argument('--stop-movement', '-m', help="Stops all CubeGrid linear and angular velocity, stopping them still. WARNING: This will affect civilian ships as well, may lead to a buildup of civilian ships as they rely on inertia to leave the sector.", default=False, action='store_true')
    argparser.add_argument('--remove-npc-ships', '-n', help='Removes any ship with inertial dampners turned off and have a beacon named Private Sail, Business Shipment, Commercial Freighter, Mining Carriage / Transport / Hauler and Military Escort / Minelayer / Transporter. Is a rough match but the option is there.', default=False, action='store_true')
    argparser.add_argument('--ignore-joint', '-I', help="At current, the utility won't remove anything with a joint on it (e.g. motor). This restriction can be ignored but use with caution as it may leave 1-ended joints.", default=False, action='store_true')
    argparser.add_argument('--full-cleanup', '-F', help="A complete cleanup. Cleans Factions, Players, Items and all unpowered Objects. Also soft-disables factories and stops movement", default=False, action='store_true')
    argparser.add_argument('--save-asteroids', '-s', help="Saves a copy of all asteroids as they are", default=False, action='store_true')
    argparser.add_argument('--respawn-asteroids', '-r', help="If there's nothing close to the asteroids, restores them to their original state from a backup", default=False, action='store_true')
    argparser.add_argument('--cleanup-unpowered', '-u', help="When setting up a cleanup, removes objects without reactors or batteries or with unfueled reactors or dead batteries. By default, doesn't count solar panels as power", default=False, action='store_true')
    argparser.add_argument('--cleanup-include-solar', '-S', help="Normally solar panels are excluded because its impossible to confirm with certainty that it's powered. Using this switch forces them to be included in the power check.", default=False, action='store_true')
    argparser.add_argument('--cleanup-missing-attrib', '-c', help="Removes objects that are missing cubes with the given attribute, except those that have cubes that match --cleanup-missing-subtype. A list of attributes can be found on the wiki.", nargs="*", default=[])
    argparser.add_argument('--cleanup-missing-subtype', '-C', help="Removes objects that are missing cubes with the given subtype, except those that have cubes that match --cleanup-missing-attrib. A list of subtypes can be found on the wiki.", nargs="*", default=[])
    argparser.add_argument('--remove-refinery-queue', '-Q', help="As of SE 01.043, the refinery queue self-replicates and can easily get out of control and cause serious lag. This removes the 'queue' node from refineries which doesn't seem to really do anything.", default=False, action='store_true')
    argparser.add_argument('--disable-spotlights', '-L', help="Turns off all spotlights.", default=False, action='store_true')

    args = argparser.parse_args()

    print("")
    #print(args)
    #print("")

    #Definition for a full cleanup
    if args.full_cleanup:
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

    #Ok, we're good. Get the log ready
    logfilename = OpenLog()
    logger = logging.getLogger()

    if not sys.argv[1:]:
        logger.error("no actions given.")
        print(simpleusagemsg)
        raw_input("Press the ENTER key to exit.")
        sys.exit()

    if args.save_path == '':
        logger.error("No save path given.")
        print(simpleusagemsg)
        raw_input("Press the ENTER key to exit.")
        sys.exit()

    #Replace all "\" with "/" and add an "/" on the end if it's missing
    args.save_path = args.save_path.replace("\\", "/")
    if args.save_path[-1:] != "/":
        args.save_path = args.save_path + "/"

    ### Save some in-built vars ###
    savedir = args.save_path
    asteroidsnapshotdir = os.path.join(savedir, "semu-asteroid-snapshots")
    entitysnapshotdir = os.path.join(savedir, "semu-entity-snapshots")
    asteroidspawnrange = 600 #Nothing can be within this many units of an asteroid for it to safely respawn
    moonspawnrange = 200 #Nothing can be within this many units of an asteroid moon for it to safely respawn

    #Set up names
    smallsavefilename = "Sandbox.sbc"
    largesavefilename = "SANDBOX_0_0_0_.sbs"

    smallsavefilepath = os.path.join(savedir, smallsavefilename)
    largesavefilepath = os.path.join(savedir, largesavefilename)

    #Attempt to find the save folder
    if not os.path.isdir(savedir):
        logger.error("Unable to load save folder.")
        logger.info(savedir)
        sys.exit()

    #Check for save files
    if not os.path.isfile(smallsavefilepath):
        logger.error("Unable to find small save: %s" % smallsavefilename)
        sys.exit()
    if not os.path.isfile(largesavefilepath):
        logger.error("Unable to find small save: %s" % largesavefilename)
        sys.exit()

    #Save backups
    if not args.skip_backup and not args.whatif:
        logger.info("Saving backups...")
        if args.big_backup:
            timestamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            smallbackupname = "%s.%s.backup" % (smallsavefilepath, timestamp)
            largebackupname = "%s.%s.backup" % (largesavefilepath, timestamp)
        else:
            smallbackupname = os.path.join(smallsavefilepath, ".backup")
            largebackupname = os.path.join(largesavefilepath, ".backup")

        #print "Saving: " + smallbackupname
        logger.info("Saving smallsave backup...")
        shutil.copyfile(smallsavefilepath, smallbackupname)
        #print "Saving: " + largebackupname
        logger.info("Saving largesave backup...")
        shutil.copyfile(largesavefilepath, largebackupname)

    #Load saves
    logger.info("Loading %s..." % smallsavefilename)
    xmlsmallsavetree = ET.parse(smallsavefilepath)
    xmlsmallsave = xmlsmallsavetree.getroot()

    logger.info("Loading %s file..." % largesavefilename)
    xmllargesavetree = ET.parse(largesavefilepath)
    xmllargesave = xmllargesavetree.getroot()

    logger.info("Getting Started...")

    #Try to find the Sector Objects node
    if xmllargesave.find('SectorObjects') is None:
        logger.error("Unable to locate SectorObjects node!")
        sys.exit()

    sectorobjects = xmllargesave.find('SectorObjects')

    #Init the ownership table
    owningplayers = []

    #Big loop through entity list
    logger.info("===Beginning SectorObject check...===")

    #Rewrote to be more dynamic and to allow treating multiple entites / objects as one (motor joins). Lets call these 'object clusters'
    #Lets always treat things as a cluster. Even if it's a cluster of 1. Will need to modify functions to match
    #Removing clusters this way should be safe. The big concern was that if I were to start removing mid-loop, not only
    #   would my end point be changed, but so would the current position and objects would be skipped. This way,
    #   as long as touching any part of the cluster reveals the entire cluster, it will never remove backwards, always forwards
    i = 0
    while i < len(sectorobjects):
        #---If removing an entity, DO NOT i++ !!!---
        obj = sectorobjects[i]
        objectclass = FindAttrib(object)

        #print("Checking object")
        #print(objectclass)

        #---Process non-cubegrid stuff first---

        #Remove free floating objects
        if objectclass == "MyObjectBuilder_FloatingObject" and args.cleanup_items:
            #logger.info("Removing free-floating object: ",  object.find('EntityId').text)
            logger.info("Removing free-floating object: ", obj.find('EntityId').text, " ", GetFloatingItemName(object))
            sectorobjects.remove(object)
            continue #Next object

        #---CubeGrid Stuff---
        #if IsCubeGrid(object) == True:
        if objectclass == "MyObjectBuilder_CubeGrid":

            #ROTORS ARE JOINED BY PROXIMITY WHEN THE SERVER STARTS
            #UNTIL YOU FIGURE OUT HOW TO CALCULATE THIS IN THE SAVE, JUST USE A SINGLE CLUSTER PER OBJECT
            # AND IGNORE PRUNING ALL OBJECTS THAT HAVE ROTORS ATTACHED TO THEM
            #objectcluster = MapObjectCluster(sectorobjects, object) #Generate the entity cluster map
            objectcluster = [obj]

            #---Always process removal stuff before modify---
            #DO NOT REMOVE ANYTHING WITH A ROTOR OR STATOR OR PISTON unless the override is given, currently unable to map past joints

            #print(HasJoint(objectcluster))
            if not HasJoint(objectcluster) or args.ignore_joint:
                #print("Checking object: " + objectcluster[0].find('EntityId').text + " " + objectclass)
                if args.remove_npc_ships and IsClusterAnNPC(objectcluster):
                    #print "Removing NPC entity: " + " ,".join(objectcluster)
                    logger.info("! Removing NPC entity: ", obj.find('EntityId').text, " ", FindObjectName(objectcluster)) #Just until clusters get sorted
                    for o in objectcluster:
                        sectorobjects.remove(o)
                    continue #Next sector object

                if args.cleanup_unpowered or len(args.cleanup_missing_attrib) > 0 or len(args.cleanup_missing_subtype) > 0: #If its cleanup o'clock and it's a CubeGrid like a station or ship
                    #print("Do I remove this?")
                    if DoIRemoveThisCluster(objectcluster, args.cleanup_missing_attrib, args.cleanup_missing_subtype, args.cleanup_unpowered, args.cleanup_include_solar):
                        #print "Removing CubeGrid entites: " + " ,".join(objectcluster)
                        logger.info("! Removing CubeGrid") #Just until clusters get sorted
                        for o in objectcluster:
                            sectorobjects.remove(o)
                        continue #Next sector object, we're removing this one anyway
                    else:
                        logger.info("  Entity passed check")
                        #print("Object passes inspection: " + object.find('EntityId').text) #Just until clusters get sorted

            #Remove this Else when you've got joints sussed out
            else:
                pass
                #logger.info("Skipping object that has a joint: " + objectcluster[0].find('EntityId').text)

            #End of If HasJoint

            #---After processing removal stuff, THEN do modify stuff---

            #Add to owner list
            for owner in GetClusterOwners(objectcluster):
                if owner not in owningplayers:
                    owningplayers.append(owner)

            #Turn off factories
            #if args.disable_factories != '':
            if len(args.disable_factories) > 0:
                DisableFactories(objectcluster, args.disable_factories[0])

            #Remove refinery queues
            if args.remove_refinery_queue:
                RemoveRefineryQueue(objectcluster)

            #Turn off Spotlights
            if args.disable_spotlights:
                DisableSpotLights(objectcluster)

            #Stop movement
            if args.stop_movement:
                KillClusterInertia(objectcluster)

        #end CubeGrid if

        #Made it to the end without removing object, go to the next item
        i += 1

    #End SectorObjects loop

    #After cleanup, should be good to save snapshots
    #Asteroids
    if args.save_asteroids:
        logger.info("===Beginning asteroid snapshot...===")
        for obj in sectorobjects:
            if FindAttrib(object) == "MyObjectBuilder_VoxelMap":
                #Save a copy of this entity to a backup
                SaveAsteroid(object.find('Filename').text) #Don't worry about Print, SaveAsteroid will do that
    #End asteroid saving

    #Sector objects have now been cleaned up, lets thing about respawning
    #Asteroids
    if args.respawn_asteroids:
        logger.info("===Beginning asteroid respawn...===")

        #For efficiency, generate a list of what entites are where
        avoidents = []
        for obj in sectorobjects:
            if FindAttrib(object) == "MyObjectBuilder_Character" or FindAttrib(object) == "MyObjectBuilder_CubeGrid": #Only do checks for CubeGrids and players. Who cares about floating items or other asteroids.
                avoidents.append(object.find('PositionAndOrientation').find('Position').attrib) #Add the XYZ dict to the list

        #Now, loop through the asteroids and check if they should be respawned
        for obj in sectorobjects:
            if FindAttrib(object) == "MyObjectBuilder_VoxelMap":

                #Is it a moon or a large asteroid?
                ismoon = ("moon" in obj.find('Filename').text)
                spawnrange = 0

                if ismoon: spawn = moonspawnrange
                if not ismoon: spawn = asteroidspawnrange

                if CanRespawnAsteroid(avoidents, obj.find('PositionAndOrientation').find('Position').attrib, spawnrange):
                    RestoreAsteroid(object.find('Filename').text)

                else:
                    logger.info("Can't respawn asteroid, something is too close: " + obj.find('Filename').text)
    #End asteroid respawning

    #Begin player check. Must be after object check
    if args.prune_players:
        logger.info("===Beginning player check...===")

        playerlist = xmlsmallsave.find('AllPlayers')
        playerIDtoremove = []

        #This'll be slightly different because there's 2 player lists
        """
        for player in playerlist:
            playerID = player.find('PlayerId').text
            if (not playerID in owningplayers) == True and (player.find('IsDead').text == 'true' or FindPlayerFaction(xmlsmallsave.find('Factions').find('Factions'), playerID) == None): #Doesn't own anything AND (isDead = True OR not in a faction)
                try: #Error handling for unicode names
                    logger.info("Marking player for removal: %s, %s"%(player.find('Name').text, playerID))
                except:
                    logger.info("Marking player for removal: %s, %s"%("<unicode name>", playerID))

                playerIDtoremove.append(playerID)
        """
        for player in playerlist:
            playerID = player.find('PlayerId').text
            logger.info("Checking player entry: ", playerID, " ", player.find('Name').text)
            ownsstuff = playerID in owningplayers
            isdead = player.find('IsDead').text == 'true'
            inafaction = FindPlayerFaction(xmlsmallsave.find('Factions').find('Factions'), playerID) is not None

            logger.info("Owns stuff   : ", ownsstuff)
            logger.info("Is alive     : ", not isdead)
            logger.info("Is in faction: ", inafaction)

            if not ownsstuff and (isdead or not inafaction): #Doesn't own anything AND (isDead = True OR not in a faction)
                logger.info("Marking player for removal: ", player.find('Name').text, ", ", playerID)
                playerIDtoremove.append(playerID)
        #End player list loop

        #Remove from relevant lists
        if len(playerIDtoremove) > 0: #If there's things to do
            logger.info("===Removing marked players...===")

            #AllPlayers section
            for player in playerlist[:]:
                if player.find('PlayerId').text in playerIDtoremove:
                    logger.info("Removing ", player.find('PlayerId').text, " from All Players list")
                    playerlist.remove(player)

            #Players section. Yes, there's a second one
            pllist = xmlsmallsave.find('Players')[0]
            for player in pllist[:]:
                if player.find('Value').find('PlayerId') in playerIDtoremove:
                    logger.info("Removing ", player.find('Value').find('PlayerId'), " from Players list")
                    pllist.remove(player)

            #Factions
            #Loop through members of each faction.
            for faction in xmlsmallsave.find('Factions').find('Factions'):
                factionId = faction.find('FactionId').text
                memberlist = faction.find('Members')
                joinrequests = faction.find('JoinRequests')

                #Cleanup Members
                for member in memberlist[:]:
                    if member.find('PlayerId').text in playerIDtoremove:
                        logger.info("Removing ", member.find('PlayerId').text, " from faction ", factionId, " ", faction.find('Name').text)
                        memberlist.remove(member)

                #Cleanup Join Requests
                for joinrequest in joinrequests[:]:
                    if joinrequest.find('PlayerId').text in playerIDtoremove:
                        logger.info("Removing ", joinrequest.find('PlayerId').text, " from faction request list ", factionId, " ", faction.find('Name').text)
                        joinrequests.remove(joinrequest)

            #Factions Players, yep another second one
            factionplayers = xmlsmallsave.find('Factions').find('Players')[0]
            for factionplayer in factionplayers[:]:
                if factionplayer.find('Key').text in playerIDtoremove:
                    logger.info("Removing ", factionplayer.find('Key').text, "from faction player list")
                    factionplayers.remove(factionplayer)

    #End player pruning


    #Begin checking factions. Must be after object check and player check
    if args.prune_factions:
        logger.info("===Beginning faction check...===")

        factionIDtoremove = []

        if xmlsmallsave.find('Factions') is None:
            logger.error("Unable to location the Factions node in save!")
            sys.exit()

        #Find and mark down factions to be removed
        factionlist = xmlsmallsave.find('Factions').find('Factions')
        for faction in factionlist[:]:
            if len(faction.find('Members')) == 0: #Has no members
                logger.info("Marking faction for removal, no members: ", faction.find('Name').text, ", ", faction.find('FactionId').text)
                factionIDtoremove.append(faction.find('FactionId').text)
                factionlist.remove(faction)

        logger.info("===Removing marked factions...===")

        #Skip the FactionPlayer table. Will only remove factions that have no players, so it should never even be present in the FactionPlayers list

        #Remove from Relations table
        factionrelations = xmlsmallsave.find('Factions').find('Relations')
        for factionrelation in factionrelations[:]:
            if (factionrelation.find('FactionId1').text in factionIDtoremove) or (factionrelation.find('FactionId2').text in factionIDtoremove):
                factionrelations.remove(factionrelation)

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
            for factionsubrequest in range(0, len(factionsubrequests)):
                if factionsubrequest.text in factionIDtoremove:
                    factionsubrequests.remove(factionsubrequests[i])

        requestbodytoremove.reverse()
        for i in requestbodytoremove:
            factionrequests.remove(factionrequests[i])


    #Ok, that should be all the checks, lets save it
    if not args.whatif:
        logger.info("===Saving changes...===")
        logger.info("Saving largesave...")
        xmllargesave.attrib["xmlns:xsd"] = "http://www.w3.org/2001/XMLSchema"
        xmllargesavetree.write(largesavefilepath)

        logger.info("Saving smallsave...")
        #Space Engineers freaks the fuck out if the top of the XML in the sbc file isn't juuuuuuust right
        xmlsmallsave.attrib["xmlns:xsd"] = "http://www.w3.org/2001/XMLSchema"
        xmlsmallsavetree.write(smallsavefilepath)
    else:
        logger.info("===Script complete. WhatIf was used, no action has been taken.===")

if __name__ == '__main__':
    main()
