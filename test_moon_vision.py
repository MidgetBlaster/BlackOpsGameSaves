import base64,struct
from test_ascension_vision import Game
import moon_vision as m,ascension_vision as a
class Moon(Game):
 def __init__(self):
  super().__init__();self.values=self.film+struct.pack('<138f',*([.5]*138))
 def read(self,address,size):
  if address==self.cg+a.CURRENT:return self.values
  if address==self.cg+a.NAME:return b'zombie_moonHanger18'+bytes(46)
  return super().read(address,size)
g=Moon();nml=m.capture(g)
g.values=g.film+struct.pack('<138f',*([.75]*138));moon=m.capture(g)
assert nml!=moon
for state in (nml,moon):
 g.writes.clear();m.restore(g,state)
 assert len(g.writes)==3
 assert all(d==base64.b64decode(state['values']) for _,d in g.writes)
for state in ({**nml,'map':'zombie_cosmodrome'},{**nml,'values':'AAAA'},
 {**nml,'values':base64.b64encode(g.film+struct.pack('<138f',*([float('nan')]*138))).decode()}):
 g.writes.clear()
 try:m.restore(g,state)
 except ValueError:pass
 else:raise AssertionError('Bad vision accepted')
 assert not g.writes
print('Moon pre/post teleport vision round-trip and rejection tests passed')
