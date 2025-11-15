import serial
import time
import sys
import asyncio
import logging
from yahub import Msg

# --- PROTOCOL CONSTANTS ---
FRAME_LENGTH = 13 # Start(1) + Src(1) + Dst(1) + Cmd(1) + Data(8) + Chksum(1)
START_BYTE = 0x32

# --- DECODING MAPS (Based on reverse engineering community efforts, highly simplified) ---
COMMAND_A0_DECODER = {
    0x00: "Auto", 0x01: "Cool", 0x02: "Dry", 0x03: "Fan", 0x04: "Heat",
}

def decode_temperature(byte_value : int):
  """
  Simulated temperature decoding: (value - 55) for °C.
  """
  try:
    temp = byte_value - 55
    if 15 <= temp <= 30: # Check for reasonable temp range
      return f"{temp}°C"
    return f"Raw: {byte_value} Hex:{hex(byte_value)}   "
  except TypeError:
    return "N/A"


class Nasa_frame:

  @staticmethod
  def calculate_checksum(frame_bytes):
    """
    Calculates a simple 8-bit checksum for the frame data (Sum bytes 1 through 11).
    """
    if len(frame_bytes) < FRAME_LENGTH:
        return 0
    # Sum bytes 1 through 11 (Source, Destination, Command, Data 1-8)
    checksum_sum = sum(frame_bytes[1:12])
    # Use the lower 8 bits of the sum.
    return checksum_sum & 0xFF

  def encode(src, dst, cmd, payload):
    frame = Nasa_frame()
    frame.raw_bytes = bytearray()
    frame.raw_bytes.append(src)
    frame.raw_bytes.append(dst)
    frame.raw_bytes.append(cmd)
    frame.raw_bytes.extend(payload)
    frame.raw_bytes =  - Nasa_frame.calculate_checksum(self.raw_bytes) # fix
    return frame.raw_bytes

  @staticmethod
  def decode(full_frame : bytearray):

    if len(full_frame) != FRAME_LENGTH:
      raise Exception(f"invalid frame length: {len(full_frame)}")
    if full_frame[0] != START_BYTE:
      raise Exception("invalid start byte")

    frame = Nasa_frame()
    frame.bites = full_frame
    frame.src = full_frame[1]
    frame.dst = full_frame[2]
    frame.cmd = full_frame[3]
    frame.checksum = full_frame[12]

    calculated_checksum = frame.calculate_checksum(full_frame)

    if calculated_checksum != frame.checksum:
      return None, f"Frame: {frame.bites.hex()} Checksum Mismatch! Calculated: {hex(calculated_checksum)}, Received: {hex(frame.checksum)}"

    match frame.cmd:

      # Example decoding logic for Command 52 (Status Request Response)

      case 0x50 | 0x52:
        frame.cmdDescrip = "Status Report (Cmd 52)"
        frame.set_temp  = decode_temperature(frame.bites[4+0])
        frame.room_temp = decode_temperature(frame.bites[4+1])
        frame.output_air_temp = decode_temperature(frame.bites[4+2])
        frame.power_status = "ON" if (frame.bites[4+4] & 0x80) else "OFF"
        frame.mode = COMMAND_A0_DECODER.get(frame.bites[4+3] & 0x07, f"Raw:{hex(frame.bites[4+3])}")
      # Example decoding logic for Command A0 (Control Command)
      case 0xA0:
        frame.cmdDescrip = "Control Command (Cmd A0)"
        setting_byte = frame.bites[4+1] #### & 0x1F # Assuming lower 5 bits hold temp
        frame.temp_setpoint = decode_temperature(setting_byte)
        frame.power_state = "ON" if (frame.bites[4+4] & 0xF4) == 0xF4 else "OFF"

      case _ :
        frame.cmdDescrip = "Unknown Command"

    return frame, "Success"


class YNasa:
  """
  An asynchronous task for reading the Samsung NASA RS-485 protocol.
  It uses asyncio.to_thread() to handle the blocking serial read operation.
  """
  queue = asyncio.Queue(maxsize=100)

  def __init__(self, yahub, config, root):
    self.config = config
    self.root = root
    self.yahub = yahub
    self.logger = logging.getLogger()
    self.ser = None

  def read_frame_blocking(self):
    if self.ser is None:
      raise Exception(f'Serial port not open')
    try :

      frame_buffer = bytearray()
      # Read all available data byte at a time, or block  if nothing is available immediately
      while True :
        bites = self.ser.read(self.ser.in_waiting or 1)
        if not bites:
          # Shouldn't be called Sleep to yield to the event loop if the last serial read was fast/empty
          time.sleep(10)
          if len(frame_buffer):
              self.logger.warn(f'read timeout. Discarding {frame_buffer.hex(" ")}')
              del frame_buffer[:]
          continue
        frame_buffer.extend(bites)

        # work through all available bytes until we have a frame
        while True :
          start_index = frame_buffer.find(START_BYTE)
          if start_index < 0 :
            break   # no start byte, read more bytes

          # Discard unexpected junk bytes before the start byte
          if start_index > 0:
            # Optionally log discarded junk:
            self.logger.warn(f'Discarding {frame_buffer[:start_index].hex(" ")}')
            del frame_buffer[:start_index]

                  # Have we got a full frame
          if len(frame_buffer) < FRAME_LENGTH:
            # Not enough bytes for a full frame, wait for more data
            break  # read more bytes

                  # slice full frame out of buffer
          full_frame = frame_buffer[:FRAME_LENGTH]
          # remove used bytes from buffer
          del frame_buffer[:FRAME_LENGTH]
          return full_frame
    except:
      # catch exceptions that would otherwise not be caught in coroutine
      self.logger.exception(e)


  async def run(self):
    self.logger.info('Samsung NASA Protocol RS-485 coroutine started')
    with serial.Serial(
        port=self.config.get(    self.root, 'device', '/dev/ttyUSB0'),
        baudrate=self.config.get(self.root, 'baudrate', 2400),
        parity=self.config.get(  self.root, 'parity',   serial.PARITY_EVEN),
        stopbits=self.config.get(self.root, 'stopbits', serial.STOPBITS_ONE),
        bytesize=self.config.get(self.root, 'bytesize', serial.EIGHTBITS),
        timeout=self.config.get (self.root, 'timeout',  60)
      ) as self.ser :

      self.logger.info(f"{repr(self.ser)}")

      """ read and queue nasa frames forever """
      while True :
        try:
          full_frame =  await asyncio.to_thread(self.read_frame_blocking)
          frame, status = Nasa_frame.decode(full_frame)

          if status != "Success" :
            self.logger.warn(status)
          else:
            payload = frame.bites.hex()
            msg = Msg(f"nasa/dataframe", payload)
            msg.frame = frame
            msg.timestamp = timestamp
            # measurement not specified, mesage won't be written to influx
            # put the successfully decoded frame into the asyncio Queue
            await self.queue.put(msg)
          continue    # look for the next frame

        except Exception as e:
          self.logger.exception(f"In read loop: {e}")
          raise(e)

        finally :
          pass    # serial port should be automatically closed






