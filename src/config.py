
import yaml

undefined = 42

class Config:

  def __init__(self, map):
    self.map = map
    self.extendedMap = {}
    self.keys = {}
    self.flatten(self.map, 0)

  def get(self, key, attribute, default=False):
    if key in self.extendedMap:
      parent = self.extendedMap[key]
      #print(f'parent {parent}')
      node = parent[key]
      if attribute in node :
        return node[attribute]
      if attribute in parent :
        return parent[attribute]
      if default is False :
        raise KeyError(f'{attribute} not defined at or above {key} in configuration map')
      return default
    else:
        raise KeyError(f'{key} is not in the configuration map')

  def getChildren(self, key):
    children = []
    if key in self.map :
      for k, v in self.map[key].items():  # top level
        if isinstance(v, dict):
          children.append(k)
    return children

  def flatten(self, node, depth):
    if isinstance(node, dict):
      for k, v in node.items():  # top level
        if isinstance(v, dict):
          if k in self.extendedMap:
            print(f'duplicate key "{k}"')
          self.extendedMap[k] = node
          for k2, v2 in v.items():
            if isinstance(v2, dict):
              if k2 in self.extendedMap:
                print(f'duplicate key "{k2}"')
              self.extendedMap[k2] = v

  def buildTree(self, key, parent):
    node = parent[key]
    if isinstance(node, list):
      for v in node:
        self.flatten(parent, v)

    elif isinstance(node, dict):
      for k, v in node.items():
        if k in self.keys:
          raise ValueError(f'duplicate key {k} not allowed')
        #self.keys[k] = { 'p' : parent, 'v' : v }
        self.flatten(node, v)

    else:
      self.keys[key] = { 'p' : parent, 'v' : node }

'''
  def getH(self, key, attribute, default = None):

    node = self.keys[key]
    if not node:
      raise Exception(f"Key {key} not in map")
    while True:
      if attribute in node['v'] :
        return node['v'][attribute]
      if 'p' not in node:
        return default
      node = node['p']

'''



if __name__ == "__main__":
  with open('config.yaml') as yfile:
    config = Config(yaml.safe_load(yfile)['ePaperPV'])
    #print(config.map)
  print(f'length {len(config.extendedMap)}')
  #print(f'length {config.extendedMap.keys()}')

  print(f"RegentHigh startdate {config.get('RegentHigh', 'startdate')}")
  print(f"RH-A startdate       {config.get('RH-A', 'startdate', 'not defined')}" )
  print(f"RH-A localRate       {config.get('RH-A', 'localRate', 'not defined')}" )
  print(f"RH-A apitype         {config.get('RH-A', 'apitype', 'not defined')}" )

  print(f"RegentHigh children  {config.getChildren('RegentHigh')}")
  print(f"RH-A children        {config.getChildren('RH-A')}")
