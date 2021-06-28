#!/usr/bin/ipython3 -i

import meraki
import copy
import os
import pickle

import time
import get_keys as g



db = meraki.DashboardAPI(api_key=g.get_api_key(), base_url='https://api.meraki.com/api/v1/', print_console=False)

print()

###### FILL OUT THE FOLLOWING FIELDS######################################################
dk_org_id = '123412341234' #Your ORGID

dk_netid = 'L_123412341234' #Your NetworkID

############################################################################################


#target_netid = 'L_577586652210276657' #AutoSync Clone 1

target_netid = dk_netid


AutoChannels = [36,40,44,48,52,56,60,64,100,104,108,112,116,120,124,128,132,136,140,144,149,153,157,161,165]
AutoChannelsDK = [36,40,44,48,52,56,60,64,100,104,108,112,116,132,136,140,144]

def getClear(dfs_channels):
    clearList = copy.deepcopy(AutoChannels)
    for dfs in dfs_channels:
        if dfs in clearList:
            clearList.remove(dfs)
    return clearList

def findSN(MRs, name):
    for m in MRs:
        if name.lower() in m['name'].lower():
            return m

def findNAME(MRs, serial):
    for m in MRs:
        if serial in m['serial']:
            return m

#Helper function in order to set minimal power levels via API. Below certain values, API's will error out.
def MR_rfp_pwr(RFP):
    if 'twoFourGhzSettings' in RFP:
        if 'minPower' in RFP['twoFourGhzSettings'] and RFP['twoFourGhzSettings']['minPower'] < 5:
            RFP['twoFourGhzSettings']['minPower'] = 5
        if 'maxPower' in RFP['twoFourGhzSettings'] and RFP['twoFourGhzSettings']['maxPower'] < 5:
            RFP['twoFourGhzSettings']['maxPower'] = 5
        
        #Wierd use-case where it'll break when you update via API
        if 'validAutoChannels' in RFP['twoFourGhzSettings'] and  RFP['twoFourGhzSettings']['validAutoChannels'] == [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]:
            RFP['twoFourGhzSettings']['validAutoChannels'] = [1,6,11]

    if 'fiveGhzSettings' in RFP:
        if 'minPower' in RFP['fiveGhzSettings'] and RFP['fiveGhzSettings']['minPower'] < 8:
            RFP['fiveGhzSettings']['minPower'] = 8
        if 'maxPower' in RFP['fiveGhzSettings'] and RFP['fiveGhzSettings']['maxPower'] < 8:
            RFP['fiveGhzSettings']['maxPower'] = 8
    return RFP

print()


tmp = db.networks.getNetworkEvents(dk_netid, productType='wireless', perPage=1000)
events = copy.deepcopy(tmp['events'])
for i in range(0,5):
    tmp = db.networks.getNetworkEvents(dk_netid, productType='wireless', perPage=1000, endingBefore=tmp['pageStartAt'])
    events = events + copy.deepcopy(tmp['events'])

print(f'Found total of {len(events)} events in log')

includedTypes = ['dfs_event']
includedTypes2 = ['auto_rf_channel_change','dfs_event']
tmp2 = db.networks.getNetworkEvents(dk_netid, productType='wireless', perPage=1000, includedEventTypes=includedTypes)
dfs = copy.deepcopy(tmp2['events'])

print(f'Found total of {len(dfs)} DFS events in log')

impacted = {}
chanAP = {}
APmap = {}

for d in dfs:
    if not d['deviceSerial'] in impacted:
        impacted[d['deviceSerial']] = []
    if not int(d['eventData']['channel']) in impacted[d['deviceSerial']]:
        impacted[d['deviceSerial']].append(int(d['eventData']['channel']))

for i in impacted:
    impacted[i].sort()
    iLen = len(impacted[i])
    if not iLen in chanAP:
        chanAP[iLen] = []

    if not impacted[i] in chanAP[iLen]: 
        chanAP[iLen].append(impacted[i])
    
    #if not i in chanAP[impacted[i]]:
    #    chanAP[impacted[i]].append(i)
    if not iLen in APmap:
        APmap[iLen] = []
    if not i in APmap[iLen]:
        APmap[iLen].append(i)
    

print(f'AP / DFS-Channels mapping complete')
print(impacted)

print(f'Sorted Channel/AP List')
print(chanAP)

airm = db.wireless.getNetworkWirelessAirMarshal(dk_netid)
devs = db.networks.getNetworkDevices(dk_netid)
MRs = []
for d in devs:
    if 'model' in d and 'MR' in d['model']:
        if 'firmware' in d and not 'Not running configured version' in d['firmware']:
            MRs.append(d)

sum_chanAP = {}
for c in chanAP:
    if not c in sum_chanAP:
        sum_chanAP[c] = []
    channelsList = chanAP[c]
    for cl in channelsList:
        for chan in cl:
            if not chan in sum_chanAP[c]:
                sum_chanAP[c].append(chan)
    sum_chanAP[c].sort()

for sc in sum_chanAP:
    channels = sum_chanAP[sc]
    #print(f'Active Channels: {channels}')
    clearChannels = getClear(channels)
    #print(f'Clear Channels: {clearChannels} Quantity:{len(clearChannels)}')

dk_rfps = db.wireless.getNetworkWirelessRfProfiles(dk_netid)
rfps = db.wireless.getNetworkWirelessRfProfiles(target_netid)


rfpID = {}
for i in impacted:
    print(f'Pulling RFPid from SN[{i}]')
    rfpID[i] = db.wireless.getDeviceWirelessRadioSettings(i)['rfProfileId']


rfpIDprofiles = {}
for i in rfpID:
    id = rfpID[i]
    if not id in rfpIDprofiles:
        print(f'Pulling Profile[{id}] and storing it')
        rfpIDprofiles[id] = db.wireless.getNetworkWirelessRfProfile(dk_netid, id)
        rfpIDprofiles[id].pop('id')
        rfpIDprofiles[id].pop('networkId')
        #overrides here
        if len(rfpIDprofiles[id]['twoFourGhzSettings']['validAutoChannels']) > 3:
            print(f'Yup, too long, setting to 1,6,11')
            rfpIDprofiles[id]['twoFourGhzSettings']['validAutoChannels'] = [1,6,11]


def deleteRFPs():
    #target_netid only
    tempRFPS = db.wireless.getNetworkWirelessRfProfiles(target_netid)
    for trfp in tempRFPS:
        db.wireless.deleteNetworkWirelessRfProfile(target_netid,trfp['id'])

#deleteRFPs() #only uncomment this if you want to wipe out the existing RFProfiles

for SN in rfpID:
    MR = findNAME(MRs, SN)
    name = MR['name']
    rfp_id =  rfpID[SN]
    newRFP = copy.deepcopy(rfpIDprofiles[rfp_id])
    newRFP = MR_rfp_pwr(newRFP) #fixes power levels below certain values
    newRFP['fiveGhzSettings']['validAutoChannels'] = getClear(impacted[SN])
    newID = rfp_id
    if not name in rfpIDprofiles[rfp_id]['name']:
        newRFP['name'] = name
        print(f'Name[{name}] not founding creating new RF-Profile {newRFP}')
        newID = db.wireless.createNetworkWirelessRfProfile(target_netid, **newRFP)['id']
    else:
        print(f'Serial[{SN}] is mapped to an RFP with the same name[{name}], updating that RF-Profile')
        db.wireless.updateNetworkWirelessRfProfile(target_netid, rfp_id, **newRFP)
    
    print(f'Updating Device[{SN}] with profileID[{newID}]')
    db.wireless.updateDeviceWirelessRadioSettings(SN,rfProfileId = newID)



