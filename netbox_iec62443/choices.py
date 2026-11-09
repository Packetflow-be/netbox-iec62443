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


class ConduitDirectionChoices(ChoiceSet):
    ONE_WAY = 'one-way'
    TWO_WAY = 'two-way'

    CHOICES = (
        Choice(ONE_WAY, _('One-way'), color='gray'),
        Choice(TWO_WAY, _('Two-way'), color='blue'),
    )


class ConduitAllowedChoices(ChoiceSet):
    """Is this path allowed? The verdict column of the access map."""
    YES = 'yes'
    NO = 'no'
    UNKNOWN = 'unknown'

    CHOICES = (
        Choice(YES, _('Yes'), color='green'),
        Choice(NO, _('No'), color='red'),
        Choice(UNKNOWN, _('Unknown'), color='yellow'),
    )


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

    DEFAULT_PORTS = {
        MODBUS_TCP: [502], S7COMM: [102], S7COMM_PLUS: [102], ETHERNET_IP: [44818, 2222], OPC_UA: [4840],
        OPC_DA: [135], BACNET_IP: [47808], DNP3: [20000], IEC_104: [2404], IEC_61850_MMS: [102],
        MQTT: [1883, 8883], HART_IP: [5094], KNX_IP: [3671], OMRON_FINS: [9600], MELSEC: [5007],
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
