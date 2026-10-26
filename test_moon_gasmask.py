"""Gas-mask on/off, relocated materials and unsupported-client checks."""
import struct
from contextlib import nullcontext
import moon_gasmask as m

class Game:
 def __init__(self):
  self.mem={};self.writes=[];self.cg=0x100000
  for a,h in m.CHECKS:self.put(a,bytes.fromhex(h))
  self.put(0x78BDFD,b'\x8b\x1d'+struct.pack('<I',0x90000))
  self.put(0x90000,struct.pack('<I',self.cg))
  for slot,name in enumerate(m.MATERIALS):
   ptr=0x200000+slot*0x100;nameptr=ptr+0x40
   self.put(ptr,struct.pack('<I',nameptr));self.put(nameptr,name.encode()+b'\0')
   self.put(self.cg+m.MATERIAL_MAP+slot*4,struct.pack('<I',ptr))
 def put(self,a,b):self.mem.update({a+i:v for i,v in enumerate(b)})
 def read(self,a,n):return bytes(self.mem.get(a+i,0) for i in range(n))
 def u32(self,a):return struct.unpack('<I',self.read(a,4))[0]
 def write(self,a,b):self.writes.append((a,b));self.put(a,b)
 def suspended(self):return nullcontext()

g=Game();off=m.capture(g);assert off['worn'] is False
on={**off,'worn':True}
m.restore(g,on)
assert m.capture(g)==on
assert g.u32(g.cg+m.OVERLAY_MATERIAL)==0x200100
assert g.read(g.cg+m.FILTER_ENABLED,1)==b'\1'
m.restore(g,off);assert m.capture(g)==off
for state in ({**on,'map':'zombie_cosmodrome'},{**on,'worn':1}):
 g.writes.clear()
 try:m.restore(g,state)
 except ValueError:pass
 else:raise AssertionError('Invalid state accepted')
 assert not g.writes
# Unsupported layouts do not write renderer memory.
g=Game();g.put(m.CHECKS[0][0],b'\0');g.writes.clear()
try:m.restore(g,on)
except RuntimeError:pass
else:raise AssertionError('Unverified renderer accepted')
assert not g.writes
# Missing materials never partially enable the overlay.
g=Game();g.put(g.cg+m.MATERIAL_MAP,b'\0'*8)
try:m.restore(g,on)
except RuntimeError:pass
else:raise AssertionError('Missing material accepted')
assert not g.writes
print('Moon gas-mask state and guarded rendering tests passed')
