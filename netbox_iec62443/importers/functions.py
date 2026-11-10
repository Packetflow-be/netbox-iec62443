"""
What an industrial protocol request does to the device it is sent to: read, write, control, program.

Observation files name a request's function the way the capture tool wrote it ("Write Variable",
"WRITE_SINGLE_COIL", "Force Single Coil", "DIRECT_OPERATE", "C_SC_NA_1", "Request download", ...).
`classify()` looks the function up in an explicit table per protocol; there is no substring guessing.
A function that is not in the table is UNCLASSIFIED, never silently "read". A flow can also carry its
class itself (`"access": "write"` in flows.json), which wins over the table.

  read     reads values, identity, directory or status
  write    changes values, parameters, setpoints or configuration objects
  control  operates the process or the controller: commands, run/stop, reset, restart, method calls
  program  changes the controller's logic, firmware or files: download, delete block, file write
  other    session, transport or time management (connect, keep-alive, time sync)

Write, control and program change the target; the importer reports their senders. Where a function can go
either way (a DNP3 file open, an IEC 104 file transfer) the table takes the class that changes the target.
"""
import re

READ = 'read'
WRITE = 'write'
CONTROL = 'control'
PROGRAM = 'program'
OTHER = 'other'
UNCLASSIFIED = 'unclassified'

CLASSES = (READ, WRITE, CONTROL, PROGRAM, OTHER)
MODIFYING = (WRITE, CONTROL, PROGRAM)


def _key(name):
    """'WRITE_SINGLE_COIL', 'Write Single Coil' and 'write-single-coil' all become 'writesinglecoil'."""
    return re.sub(r'[^a-z0-9]', '', str(name).lower())


def _table(**classes):
    return {_key(name): cls for cls, names in classes.items() for name in names}


# Modbus: Zeek/ICSNPP and Wireshark names, the Modicon names ("Force", "Preset") and the function codes
MODBUS = _table(
    read=(
        'Read Coils', 'Read Discrete Inputs', 'Read Holding Registers', 'Read Input Registers',
        'Read Exception Status', 'Get Comm Event Counter', 'Get Comm Event Log', 'Report Slave ID',
        'Report Server ID', 'Read File Record', 'Read FIFO Queue', 'Read Device Identification',
        'Read Coil Status', 'Read Input Status',
        '1', '2', '3', '4', '7', '11', '12', '17', '20', '24',
    ),
    write=(
        'Write Single Coil', 'Write Single Register', 'Write Multiple Coils', 'Write Multiple Registers',
        'Write File Record', 'Mask Write Register', 'Read Write Multiple Registers', 'Read/Write Multiple Registers',
        'Force Single Coil', 'Force Multiple Coils', 'Preset Single Register', 'Preset Multiple Registers',
        '5', '6', '15', '16', '21', '22', '23',
    ),
    control=('Diagnostics', 'Diagnostic', '8'),
    other=('Encapsulated Interface Transport', 'Encap Interface Transport', '43'),
)

# S7comm: Wireshark and ICSNPP job functions and PLC control
S7COMM = _table(
    read=('Read Var', 'Read Variable', 'Start Upload', 'Upload', 'End Upload', 'Read SZL', 'Block Functions'),
    write=('Write Var', 'Write Variable'),
    control=('PLC Control', 'PLC Stop', 'PI-Service', 'PI Service'),
    program=('Request Download', 'Download Block', 'Download Ended', 'Download', 'Delete Block', 'Insert Block'),
    other=('Setup Communication', 'Setup Comm', 'Userdata', 'Ack', 'Ack Data', 'Job', 'CPU Services', 'Time Functions'),
)

# S7comm-plus opcodes and functions
S7COMM_PLUS = _table(
    read=('Explore', 'GetMultiVariables', 'GetVariable', 'GetVarSubStreamed', 'GetLink'),
    write=('SetMultiVariables', 'SetVariable', 'SetVarSubStreamed', 'CreateObject', 'DeleteObject', 'AddLink',
           'RemoveLink'),
    control=('Invoke',),
    other=('BeginSequence', 'EndSequence', 'Notification', 'Request', 'Response', 'Response2'),
)

# EtherNet/IP encapsulation commands and CIP services (ICSNPP enip/cip logs)
ETHERNET_IP = _table(
    read=(
        'Get Attribute All', 'Get Attributes All', 'Get Attribute List', 'Get Attribute Single', 'Get Member',
        'Find Next Object Instance', 'Read Tag', 'Read Tag Fragmented', 'Get Instance Attribute List',
        'List Identity', 'List Services', 'List Interfaces',
    ),
    write=(
        'Set Attribute All', 'Set Attributes All', 'Set Attribute List', 'Set Attribute Single', 'Set Member',
        'Insert Member', 'Remove Member', 'Apply Attributes', 'Create', 'Delete', 'Save', 'Restore',
        'Write Tag', 'Write Tag Fragmented', 'Read Modify Write Tag',
    ),
    control=('Reset', 'Start', 'Stop'),
    other=(
        'No Operation', 'NOP', 'Register Session', 'Unregister Session', 'Send RR Data', 'Send Unit Data',
        'Unconnected Send', 'Forward Open', 'Large Forward Open', 'Forward Close', 'Multiple Service Packet',
        'Group Sync',
    ),
)

# DNP3 application function codes (Zeek dnp3.log fc_request)
DNP3 = _table(
    read=('Read', 'Get File Info'),
    write=('Write', 'Assign Class', 'Enable Unsolicited', 'Disable Unsolicited', 'Save Config'),
    control=(
        'Select', 'Operate', 'Direct Operate', 'Direct Operate NR', 'Immed Freeze', 'Immed Freeze NR',
        'Freeze Clear', 'Freeze Clear NR', 'Freeze At Time', 'Freeze At Time NR', 'Cold Restart', 'Warm Restart',
        'Initialize Data', 'Initialize Appl', 'Start Appl', 'Stop Appl',
    ),
    program=('Open File', 'Delete File', 'Activate Config'),
    other=(
        'Confirm', 'Response', 'Unsolicited Response', 'Delay Measure', 'Record Current Time', 'Close File',
        'Abort File', 'Authenticate File', 'Authenticate Req', 'Authenticate Req NR', 'Authenticate Err',
    ),
)

# IEC 60870-5-104 / -101: ASDU type identifiers by their two-letter group, e.g. C_SC_NA_1 -> "SC"
IEC_104_TYPES = {
    'C': {'SC': CONTROL, 'DC': CONTROL, 'RC': CONTROL, 'RP': CONTROL, 'SE': WRITE, 'BO': WRITE,
          'IC': READ, 'CI': READ, 'RD': READ, 'CS': OTHER, 'TS': OTHER},
    'P': {'ME': WRITE, 'AC': WRITE},
    # File transfer can run either way; without the direction it counts as program (conservative)
    'F': {'FR': PROGRAM, 'SR': PROGRAM, 'SC': PROGRAM, 'LS': PROGRAM, 'AF': PROGRAM, 'SG': PROGRAM, 'DR': READ},
    'M': {},  # monitor direction: everything is a report (read)
}
IEC_104 = _table(
    read=('Interrogation Command', 'General Interrogation', 'Counter Interrogation Command', 'Read Command'),
    write=('Set Point Command', 'Setpoint Command', 'Bitstring Command', 'Parameter Activation'),
    control=('Single Command', 'Double Command', 'Regulating Step Command', 'Reset Process Command'),
    other=('Clock Synchronization Command', 'Test Command', 'STARTDT', 'STOPDT', 'TESTFR', 'S-Format', 'U-Format'),
)
_IEC_TYPE_ID = re.compile(r'^([CMPF])_([A-Z]{2})_[A-Z]{2}_1$')

# IEC 61850 MMS confirmed services
MMS = _table(
    read=(
        'Read', 'GetNameList', 'GetVariableAccessAttributes', 'GetNamedVariableListAttributes', 'Identify', 'Status',
        'FileOpen', 'FileRead', 'FileClose', 'FileDirectory', 'GetDomainAttributes', 'InitiateUploadSequence',
        'UploadSegment', 'TerminateUploadSequence', 'InformationReport',
    ),
    write=('Write', 'DefineNamedVariableList', 'DeleteNamedVariableList'),
    control=('Start', 'Stop', 'Resume', 'Reset', 'Kill', 'CreateProgramInvocation', 'DeleteProgramInvocation'),
    program=(
        'InitiateDownloadSequence', 'DownloadSegment', 'TerminateDownloadSequence', 'DeleteDomain', 'ObtainFile',
        'FileDelete', 'FileRename',
    ),
    other=('Initiate', 'Conclude', 'Cancel', 'Abort'),
)

# OPC UA services, with or without the "Request" suffix (ICSNPP opcua-binary)
OPC_UA = _table(
    read=(
        'Read', 'Browse', 'BrowseNext', 'HistoryRead', 'TranslateBrowsePathsToNodeIds', 'RegisterNodes',
        'UnregisterNodes', 'GetEndpoints', 'FindServers', 'FindServersOnNetwork', 'QueryFirst', 'QueryNext',
        'CreateSubscription', 'ModifySubscription', 'DeleteSubscriptions', 'TransferSubscriptions', 'SetPublishingMode',
        'CreateMonitoredItems', 'ModifyMonitoredItems', 'DeleteMonitoredItems', 'SetMonitoringMode', 'SetTriggering',
        'Publish', 'Republish',
    ),
    write=('Write', 'HistoryUpdate', 'AddNodes', 'DeleteNodes', 'AddReferences', 'DeleteReferences'),
    control=('Call',),
    other=('OpenSecureChannel', 'CloseSecureChannel', 'CreateSession', 'ActivateSession', 'CloseSession', 'Cancel',
           'Hello', 'Acknowledge'),
)

# BACnet services (Zeek/ICSNPP bacnet.log pdu_service)
BACNET = _table(
    read=(
        'Read-Property', 'Read-Property-Multiple', 'Read-Range', 'Atomic-Read-File', 'Who-Is', 'I-Am', 'Who-Has',
        'I-Have', 'Subscribe-COV', 'Subscribe-COV-Property', 'Get-Alarm-Summary', 'Get-Event-Information',
        'Get-Enrollment-Summary',
    ),
    write=(
        'Write-Property', 'Write-Property-Multiple', 'Create-Object', 'Delete-Object', 'Add-List-Element',
        'Remove-List-Element', 'Write-Group',
    ),
    control=('Device-Communication-Control', 'Reinitialize-Device'),
    program=('Atomic-Write-File',),
    other=(
        'Time-Synchronization', 'UTC-Time-Synchronization', 'Confirmed-Private-Transfer',
        'Unconfirmed-Private-Transfer', 'Acknowledge-Alarm', 'Confirmed-COV-Notification',
        'Unconfirmed-COV-Notification', 'Confirmed-Event-Notification', 'Unconfirmed-Event-Notification',
    ),
)

# Omron FINS commands, by name and by MRC/SRC code
OMRON_FINS = _table(
    read=(
        'Memory Area Read', 'Multiple Memory Area Read', 'Parameter Area Read', 'Program Area Read',
        'Controller Data Read', 'Controller Status Read', 'Cycle Time Read', 'Clock Read', 'File Name Read',
        'Single File Read', '0101', '0104', '0201', '0306', '0501', '0601', '0620', '0701', '2201', '2202',
    ),
    write=('Memory Area Write', 'Memory Area Fill', 'Memory Area Transfer', 'Parameter Area Write',
           'Parameter Area Clear', 'Clock Write', '0102', '0103', '0105', '0202', '0203', '0702'),
    control=('Run', 'Stop', 'Forced Set/Reset', 'Forced Set/Reset Cancel', '0401', '0402', '2301', '2302'),
    program=('Program Area Write', 'Program Area Clear', 'Single File Write', 'File Delete', 'Memory Card Format',
             '0307', '0308', '2203', '2205'),
)

TABLES = {
    'modbus-tcp': MODBUS, 'modbus-rtu': MODBUS, 'modbus-ascii': MODBUS,
    's7comm': S7COMM, 's7comm-plus': S7COMM_PLUS,
    'ethernet-ip': ETHERNET_IP,
    'dnp3': DNP3,
    'iec-104': IEC_104, 'iec-101': IEC_104,
    'iec-61850-mms': MMS,
    'opc-ua': OPC_UA,
    'bacnet-ip': BACNET, 'bacnet-mstp': BACNET,
    'omron-fins': OMRON_FINS,
}


def classify(protocol, func):
    """
    Class of a request: READ, WRITE, CONTROL, PROGRAM, OTHER, or UNCLASSIFIED when the function is empty or
    not in this protocol's table. `protocol` is a plugin protocol value (IndustrialProtocolChoices).
    """
    if func is None or str(func).strip() == '':
        return UNCLASSIFIED
    func = str(func).strip()
    if protocol in ('iec-104', 'iec-101'):
        match = _IEC_TYPE_ID.match(func.upper())
        if match:
            direction, group = match.groups()
            if direction == 'M':
                return READ
            return IEC_104_TYPES[direction].get(group, UNCLASSIFIED)
    table = TABLES.get(protocol, {})
    key = _key(func)
    if protocol == 'opc-ua' and key.endswith('request') and key != 'request':
        key = key[:-len('request')]
    return table.get(key, UNCLASSIFIED)
