import logging
import asyncio
from yahub import Msg
from typing import Any


class AsyncioQueueLogHandler(logging.Handler):
  """
  A logging handler that puts log records into an asyncio.Queue.

  This allows asynchronous processing of log messages, preventing the
  logging call from blocking the main thread/event loop.
  """
  def __init__(self):
    """
    Initializes the AsyncioQueueLogHandler.

    Args:
        queue: The asyncio.Queue instance where log records will be placed.
        *args: Additional arguments for the base logging.Handler.
        **kwargs: Additional keyword arguments for the base logging.Handler.
    """
    super().__init__()
    self.listeners = []
    self.queue = asyncio.Queue(maxsize=100)

  def addListener(self, listener):
    self.listeners.append(listener)

  def emit(self, record: logging.LogRecord) -> None:
    """
    Emits a log record by putting it into the asyncio.Queue.

    This method is called by the logging system for each log message.
    It uses a non-blocking put_nowait() to avoid blocking the event loop.
    If the queue is full, the message might be dropped, or it might
    raise an asyncio.QueueFull exception depending on the queue's maxsize.
    For simplicity, we'll catch QueueFull and log an error to stderr,
    as the primary logger might also be using this queue.
    """
    try:
      # We use put_nowait because emit is a synchronous method and
      # we don't want to block the thread/event loop it's called from.
      self.queue.put_nowait(record)

    except asyncio.QueueFull:
      # This handles cases where the queue's maxsize is hit.
      # It's important not to try logging this with the same logger
      # as it could lead to infinite recursion.
      pass

    except Exception:
        # Handle other potential errors during emission
        self.handleError(record)



  async def run(self):
    # self.logger.debug('coroutine started')

    while True :
      record = await self.queue.get()
      texxt = self.formatter.format(record)

      msg = Msg('sys.log', texxt)
      for listener in self.listeners:
          listener.enqueue(msg)
      self.queue.task_done()
      await asyncio.sleep(0.5)        # limit the message rate to 2 in case there's loooping


async def log_consumer(queue: asyncio.Queue):
    """
    An asynchronous function to consume log records from the queue and process them.
    """
    print("Log consumer started...")
    while True:
        record = await queue.get()
        # Process the log record here. For demonstration, we'll format and print it.
        # In a real application, you might write it to a file, send it to a remote service, etc.
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        formatted_message = formatter.format(record)
        print(f"Consumed Log: {formatted_message}")
        queue.task_done()
        await asyncio.sleep(0.01) # Small sleep to yield control, if needed

async def main():
    """
    Main function to set up the logger, handler, and run the consumer.
    """
    # 1. Create an asyncio Queue
    log_queue = asyncio.Queue(maxsize=100) # Limit queue size to prevent unbounded growth

    # 2. Instantiate the custom handler with the queue
    queue_handler = AsyncioQueueLogHandler(log_queue)

    # 3. Get a logger and add the handler
    logger = logging.getLogger('my_app_logger')
    logger.setLevel(logging.INFO)
    logger.addHandler(queue_handler)

    # Optionally, add another handler for immediate console output for critical issues
    # or just for debugging during development.
    # console_handler = logging.StreamHandler()
    # console_handler.setLevel(logging.WARNING) # Only warnings and above go to console immediately
    # formatter = logging.Formatter('%(name)s - %(levelname)s - %(message)s')
    # console_handler.setFormatter(formatter)
    # logger.addHandler(console_handler)

    # 4. Start the log consumer as a background task
    consumer_task = asyncio.create_task(log_consumer(log_queue))

    # 5. Emit some log messages
    logger.info("This is an informational message.")
    logger.warning("This is a warning message.")
    logger.debug("This debug message will not be handled by the logger due to level.") # Won't show up
    logger.error("An error occurred: %s", "File not found")

    # Simulate some application work
    for i in range(5):
        logger.info(f"Processing item {i}")
        await asyncio.sleep(0.1)

    logger.critical("Application is shutting down.")

    # Give the consumer a moment to process remaining messages
    await log_queue.join() # Wait until all items in the queue have been processed

    # Cancel the consumer task
    consumer_task.cancel()
    try:
        await consumer_task
    except asyncio.CancelledError:
        print("Log consumer cancelled.")

    print("Main application finished logging.")

if __name__ == "__main__":
    # Ensure a proper event loop is running to use asyncio.Queue
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Application interrupted.")

