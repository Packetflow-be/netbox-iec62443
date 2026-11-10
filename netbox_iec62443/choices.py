from django.utils.translation import gettext_lazy as _

from utilities.choices import Choice, ChoiceSet


class PurdueLevelChoices(ChoiceSet):
    """Purdue reference model levels, as used by IEC 62443 and most OT asset tools."""
    LEVEL_0 = '0'
    LEVEL_1 = '1'
    LEVEL_2 = '2'
    LEVEL_3 = '3'
    LEVEL_3_5 = '3.5'
    LEVEL_4 = '4'
    LEVEL_5 = '5'

    CHOICES = (
        Choice(LEVEL_0, _('0 - Process (sensors, actuators)'), color='purple'),
        Choice(LEVEL_1, _('1 - Basic control (PLC, RTU)'), color='red'),
        Choice(LEVEL_2, _('2 - Supervisory (HMI, SCADA, engineering)'), color='orange'),
        Choice(LEVEL_3, _('3 - Site operations'), color='yellow'),
        Choice(LEVEL_3_5, _('3.5 - Industrial DMZ'), color='cyan'),
        Choice(LEVEL_4, _('4 - Business / office'), color='blue'),
        Choice(LEVEL_5, _('5 - Enterprise / internet'), color='gray'),
    )

    @classmethod
    def at_or_below(cls, level):
        """All level values numerically <= level (e.g. '2' -> ['0', '1', '2'])."""
        limit = float(level)
        return [value for value, _label in cls.CHOICES if float(value) <= limit]


class SecurityLevelChoices(ChoiceSet):
    """IEC 62443-3-3 security levels (used here as the zone's target, SL-T)."""
    SL_0 = 0
    SL_1 = 1
    SL_2 = 2
    SL_3 = 3
    SL_4 = 4

    CHOICES = (
        Choice(SL_0, _('SL 0 - No specific requirement')),
        Choice(SL_1, _('SL 1 - Casual or coincidental violation')),
        Choice(SL_2, _('SL 2 - Intentional, simple means')),
        Choice(SL_3, _('SL 3 - Intentional, sophisticated means')),
        Choice(SL_4, _('SL 4 - Intentional, sophisticated means, extended resources')),
    )


class ZoneTypeChoices(ChoiceSet):
    """What kind of zone this is. An MSP or supplier is an external zone; a flow from it is remote access."""
    OT = 'ot'
    SAFETY = 'safety'
    DMZ = 'dmz'
    ENTERPRISE = 'enterprise'
    EXTERNAL = 'external'

    CHOICES = (
        Choice(OT, _('OT (control)'), color='red'),
        Choice(SAFETY, _('Safety (SIS)'), color='purple'),
        Choice(DMZ, _('DMZ'), color='cyan'),
        Choice(ENTERPRISE, _('Enterprise'), color='blue'),
        Choice(EXTERNAL, _('External / supplier'), color='gray'),
    )


class FlowAllowedChoices(ChoiceSet):
    """Is this flow allowed? The verdict column of the access map."""
    YES = 'yes'
    NO = 'no'
    UNKNOWN = 'unknown'

    CHOICES = (
        Choice(YES, _('Yes'), color='green'),
        Choice(NO, _('No'), color='red'),
        Choice(UNKNOWN, _('Unknown'), color='yellow'),
    )


class AccessChoices(ChoiceSet):
    """What a flow's requests do to the destination (see importers/functions.py)."""
    READ = 'read'
    WRITE = 'write'
    CONTROL = 'control'
    PROGRAM = 'program'
    OTHER = 'other'

    CHOICES = (
        Choice(READ, _('Read'), color='green'),
        Choice(WRITE, _('Write'), color='orange'),
        Choice(CONTROL, _('Control'), color='red'),
        Choice(PROGRAM, _('Program'), color='purple'),
        Choice(OTHER, _('Other'), color='gray'),
    )
    # Classes that change the destination
    MODIFYING = (WRITE, CONTROL, PROGRAM)


class IndustrialProtocolChoices(ChoiceSet):
    """Industrial protocols. `DEFAULT_PORTS` are the usual TCP/UDP ports; `SERIAL` run on a fieldbus."""
    MODBUS_TCP = 'modbus-tcp'
    MODBUS_RTU = 'modbus-rtu'
    MODBUS_ASCII = 'modbus-ascii'
    S7COMM = 's7comm'
    S7COMM_PLUS = 's7comm-plus'
    PROFINET = 'profinet'
    PROFIBUS_DP = 'profibus-dp'
    ETHERNET_IP = 'ethernet-ip'
    OPC_UA = 'opc-ua'
    OPC_DA = 'opc-da'
    BACNET_IP = 'bacnet-ip'
    BACNET_MSTP = 'bacnet-mstp'
    DNP3 = 'dnp3'
    IEC_104 = 'iec-104'
    IEC_101 = 'iec-101'
    IEC_61850_MMS = 'iec-61850-mms'
    IEC_61850_GOOSE = 'iec-61850-goose'
    MQTT = 'mqtt'
    HART_IP = 'hart-ip'
    ETHERCAT = 'ethercat'
    CANOPEN = 'canopen'
    KNX_IP = 'knx-ip'
    OMRON_FINS = 'omron-fins'
    MELSEC = 'melsec'
    OTHER = 'other'

    CHOICES = (
        (_('Modbus'), (
            (MODBUS_TCP, 'Modbus TCP'),
            (MODBUS_RTU, 'Modbus RTU'),
            (MODBUS_ASCII, 'Modbus ASCII'),
        )),
        (_('Siemens / PROFIBUS & PROFINET'), (
            (S7COMM, 'S7comm'),
            (S7COMM_PLUS, 'S7comm-plus'),
            (PROFINET, 'PROFINET IO'),
            (PROFIBUS_DP, 'PROFIBUS DP'),
        )),
        (_('CIP / OPC'), (
            (ETHERNET_IP, 'EtherNet/IP (CIP)'),
            (OPC_UA, 'OPC UA'),
            (OPC_DA, 'OPC DA (DCOM)'),
        )),
        (_('Utilities and buildings'), (
            (DNP3, 'DNP3'),
            (IEC_104, 'IEC 60870-5-104'),
            (IEC_101, 'IEC 60870-5-101'),
            (IEC_61850_MMS, 'IEC 61850 MMS'),
            (IEC_61850_GOOSE, 'IEC 61850 GOOSE'),
            (BACNET_IP, 'BACnet/IP'),
            (BACNET_MSTP, 'BACnet MS/TP'),
            (KNX_IP, 'KNXnet/IP'),
        )),
        (_('Other'), (
            (MQTT, 'MQTT'),
            (HART_IP, 'HART-IP'),
            (ETHERCAT, 'EtherCAT'),
            (CANOPEN, 'CANopen'),
            (OMRON_FINS, 'Omron FINS'),
            (MELSEC, 'Mitsubishi MELSEC (SLMP)'),
            (OTHER, _('Other')),
        )),
    )

    # The protocol's usual listening ports as NetBox port mappings ("tcp/502"). Layer-2 protocols (PROFINET RT,
    # GOOSE, EtherCAT) and serial ones have none; PROFINET's entry is its connection manager (DCE/RPC).
    DEFAULT_PORT_MAPPINGS = {
        MODBUS_TCP: ['tcp/502'], S7COMM: ['tcp/102'], S7COMM_PLUS: ['tcp/102'],
        ETHERNET_IP: ['tcp/44818', 'udp/2222'], OPC_UA: ['tcp/4840'], OPC_DA: ['tcp/135'], BACNET_IP: ['udp/47808'],
        DNP3: ['tcp/20000'], IEC_104: ['tcp/2404'], IEC_61850_MMS: ['tcp/102'], MQTT: ['tcp/1883', 'tcp/8883'],
        HART_IP: ['tcp/5094', 'udp/5094'], KNX_IP: ['udp/3671'], OMRON_FINS: ['udp/9600'], MELSEC: ['tcp/5007'],
        PROFINET: ['udp/34964'],
    }
    # The transport a protocol runs over when only a port number is known (default tcp)
    TRANSPORT = {BACNET_IP: 'udp', KNX_IP: 'udp', OMRON_FINS: 'udp', PROFINET: 'udp'}
    DEFAULT_PORTS = {
        protocol: [int(m.split('/')[1]) for m in mappings] for protocol, mappings in DEFAULT_PORT_MAPPINGS.items()
    }
    # Serial or fieldbus protocols: no IP ports; they sit on a Fieldbus with a station address
    SERIAL = (MODBUS_RTU, MODBUS_ASCII, PROFIBUS_DP, BACNET_MSTP, IEC_101, CANOPEN)


class ServiceRoleChoices(ChoiceSet):
    SERVER = 'server'
    CLIENT = 'client'
    BOTH = 'both'
    PUBLISHER = 'publisher'
    SUBSCRIBER = 'subscriber'

    CHOICES = (
        Choice(SERVER, _('Server / slave / outstation'), color='blue'),
        Choice(CLIENT, _('Client / master'), color='purple'),
        Choice(BOTH, _('Both'), color='gray'),
        Choice(PUBLISHER, _('Publisher'), color='teal'),
        Choice(SUBSCRIBER, _('Subscriber'), color='cyan'),
    )


class FieldbusMediumChoices(ChoiceSet):
    RS485 = 'rs-485'
    RS422 = 'rs-422'
    RS232 = 'rs-232'
    PROFIBUS = 'profibus'
    CAN = 'can'
    HART = 'hart'
    ASI = 'as-i'
    IO_LINK = 'io-link'
    OTHER = 'other'

    CHOICES = (
        (RS485, 'RS-485'),
        (RS422, 'RS-422'),
        (RS232, 'RS-232'),
        (PROFIBUS, _('PROFIBUS (RS-485)')),
        (CAN, 'CAN'),
        (HART, _('HART (4-20 mA)')),
        (ASI, 'AS-Interface'),
        (IO_LINK, 'IO-Link'),
        (OTHER, _('Other')),
    )


class FlowProtocolChoices(ChoiceSet):
    """Application protocol of a flow: the industrial protocols plus the IT protocols seen on OT paths."""
    RDP = 'rdp'
    SSH = 'ssh'
    TELNET = 'telnet'
    VNC = 'vnc'
    TEAMVIEWER = 'teamviewer'
    ANYDESK = 'anydesk'
    IPSEC = 'ipsec'
    OPENVPN = 'openvpn'
    WIREGUARD = 'wireguard'
    HTTP = 'http'
    HTTPS = 'https'
    SMB = 'smb'
    DNS = 'dns'
    NTP = 'ntp'
    SNMP = 'snmp'
    SYSLOG = 'syslog'

    CHOICES = IndustrialProtocolChoices.CHOICES[:-1] + (
        (_('Remote access'), (
            (RDP, 'RDP'),
            (SSH, 'SSH'),
            (TELNET, 'Telnet'),
            (VNC, 'VNC'),
            (TEAMVIEWER, 'TeamViewer'),
            (ANYDESK, 'AnyDesk'),
            (IPSEC, 'IPsec (IKE)'),
            (OPENVPN, 'OpenVPN'),
            (WIREGUARD, 'WireGuard'),
        )),
        (_('IT services'), (
            (HTTP, 'HTTP'),
            (HTTPS, 'HTTPS'),
            (SMB, 'SMB'),
            (DNS, 'DNS'),
            (NTP, 'NTP'),
            (SNMP, 'SNMP'),
            (SYSLOG, 'Syslog'),
        )),
    ) + IndustrialProtocolChoices.CHOICES[-1:]

    DEFAULT_PORT_MAPPINGS = {
        **IndustrialProtocolChoices.DEFAULT_PORT_MAPPINGS,
        RDP: ['tcp/3389'], SSH: ['tcp/22'], TELNET: ['tcp/23'], VNC: ['tcp/5900'], TEAMVIEWER: ['tcp/5938'],
        ANYDESK: ['tcp/7070'], IPSEC: ['udp/500', 'udp/4500'], OPENVPN: ['udp/1194'], WIREGUARD: ['udp/51820'],
        HTTP: ['tcp/80'], HTTPS: ['tcp/443'], SMB: ['tcp/445'], DNS: ['udp/53'], NTP: ['udp/123'],
        SNMP: ['udp/161'], SYSLOG: ['udp/514'],
    }
    TRANSPORT = {
        **IndustrialProtocolChoices.TRANSPORT,
        IPSEC: 'udp', OPENVPN: 'udp', WIREGUARD: 'udp', DNS: 'udp', NTP: 'udp', SNMP: 'udp', SYSLOG: 'udp',
    }
