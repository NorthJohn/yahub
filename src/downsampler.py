
import time, math, logging

class TopicContext:
  payload = 0.0    # last payload
  mean = 0.0
  lastMean = 0.0
  reportedMean = 0.0
  numSamples = 0
  begin = True
  def __repr__(self):
    return f"payload:{self.payload} mean:{self.mean} reportedMean:{self.reportedMean} numSamples:{self.numSamples} begin:{self.begin}"


toFix = lambda x, y : x

class Downsampler:

  def __init__(self):
    self.storeMap = {}
    self.logger = logging.getLogger()

  def digest(self, msg):
    topic = msg.topic

    # conditions to reset the store
    #print(self.storeMap)
    store = self.storeMap[topic] if topic in self.storeMap else TopicContext()
    if getattr(msg, 'reset', False):
      store = TopicContext()

    dateNow = math.floor(time.time())   # no rounding

    # check to see how much payload has changed,  *** lastMean isn't set but not using percentages

    #percentageDiff = (msg.payload - store.reportedMean) * 100 * 2 / (msg.payload + store.lastMean) if store.numSamples else 0.0;

    valueDiff1 = abs(msg.payload - store.reportedMean) if store.numSamples else 0.0;
    #breakpoint()
    valueDiff2 = abs(msg.payload - store.payload)
    valueTrigger = max(valueDiff1, valueDiff2) > getattr(msg, 'reportOnDiff', 0) ;

    # check if maxPeriod has been reached

    timeDiff = 0; timeDiffLog = '' ; timeTrigger = False ;
    if hasattr(msg, 'maxPeriodSecs'):
      if not hasattr(store, 'timestamp'):
        store.timestamp = dateNow
      if not hasattr(msg, 'timestamp'):
        msg.timestamp = dateNow;
      timeDiff = msg.timestamp - store.timestamp ;
      timeDiffLog = f'Δt:{round(timeDiff / 1000) }'
      timeTrigger = timeDiff > (msg.maxPeriodSecs * 1000);

    # check if window size has been reached

    windowSizeTrigger = store.numSamples + 1 >= getattr(msg, 'windowSize', 10000)

    endTransition = valueTrigger or timeTrigger or windowSizeTrigger  # write every maxGap
    triggers = 'triggers: ' + ("vt " if valueTrigger else "")  +  ("tt " if timeTrigger else "") + ("ws " if windowSizeTrigger else "");

    # to do put triggers into object
    # node.error(`my error message ${msg.topic} ${triggers} ${msg.payload} ${valueDiff1} ${valueDiff2}`, msg);

    store.payload = msg.payload;
    store.mean = (store.mean * store.numSamples + msg.payload) / (store.numSamples + 1)
    storeMeanView = toFix(store.mean, getattr(msg, 'precision', 2))
    store.numSamples += 1;
    msg.numSamples = store.numSamples;
    #print(f'3 {store}')
    #breakpoint()

    #const statusText = `${msg.topic} ${msg.payload} mean:${storeMeanView} num:${store.numSamples} ${timeDiffLog}`

    #node.log(`${msg.topic} ${msg.lastPayload} mean: ${store.mean.toFixed(2)}, `
    #        + `diff% ${percentageDiff}% diff:${valueDiff} numSamples:${msg.numSamples} `
    #        + `bt ${beginTransition} et ${ endTransition }`);

    printIt = lambda name, x : print(f'{name}: {x}')

    #printIt('store.begin', store.begin)
    #printIt('endTransition', endTransition)

    if (store.begin or endTransition):
      msg.payload = storeMeanView ;
      store.reportedMean = store.mean ;  # don't need to reset store.mean because numSamples is zero
      store.numSamples = 0 ;
      store.timestamp = dateNow ;
      store.begin = False ;

    # const colour = endTransition ? 'red' : 'blue'
    # nodeStatus = { fill: colour, shape: "dot", text: statusText};

    self.storeMap[topic] = store
    self.logger.debug(store)
    return msg if endTransition else None;


from yahub import Msg

if __name__ == "__main__":

  d = Downsampler()
  mean = 0.0
  for value in range(0,20):
    msg = Msg('abc', value)
    msg.payload = value
    mean += value
    #msg.reportOnDiff = 2.5
    res =  d.digest(msg)

    print(f"{value} {res.payload if res else ''}")

