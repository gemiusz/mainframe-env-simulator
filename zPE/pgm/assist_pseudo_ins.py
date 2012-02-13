# defines Pseudo-Instructions offered by ASSIST
import zPE

### add types supporting Pseudo-Instructions
from zPE.core.asm import InstructionType, OpConst, R, I, S, X, L

# int_16 => ( '', 'dddd' )
class D(InstructionType):
    def __init__(self, arg_pos, val = None):
        super(D, self).__init__('D', arg_pos)

        if val == None:
            self.valid = False
            self.__val = None
        else:
            self.set(val)

    def __len__(self):
        return 4                # number of half-bytes / hex-digits

    def get(self):
        if self.valid:
            return self.__val
        else:
            raise ValueError('value is invalid (non-initialized).')

    def prnt(self):
        if self.valid:
            rv = '{0:0>4}'.format(hex(self.__val)[2:].upper())
        else:
            rv = '----'
        return ( '', rv, )

    def value(self):
        if self.valid:
            rv = self.__val
        else:
            rv = None
        return rv

    def set(self, val):
        if not 0x0000 <= val <= 0xFFFF:
            raise ValueError('length offset must be between 0 and 65535')
        self.__val = val
        self.valid = True


### Pseudo-Instruction Mapping

PSEUDO_INS = {
    'XDUMP' : lambda argc: (
        ('E160', OpConst(S(1).ro(), 0, ), OpConst(D(2).ro(), 0, ), ),
        ('E060', S(1).ro(), OpConst(D(2).ro(), 4, ), ),
        ('E060', S(1).ro(), D(2).ro(), ),
        )[argc],
    }


### Pseudo-Instruction OP-Code Mapping

PSEUDO_OP = {
    'E160' : ( 4, lambda s : __xdump_reg() ),
    'E060' : ( 4, lambda s : __xdump(s[0], s[1:4], s[4:]) ),
    }

# internal functions supporting Pseudo-Instructions
from zPE.core.reg import GPR, SPR, Register
from zPE.core.mem import Memory
from zPE.core.cpu import __addr_reg

X_MACRO_VAR = {
    'snape_cnt' : 0,            # number of times XSNAP get called
    }

def __xdump_reg():
    reg_list = [ '    {0}'.format(r) for r in GPR ]
    __xsnap_header('REGISTERS')
    __xout('XSNAPOUT', '0', ' REGS 0-7  ', *(reg_list[:8] + [ '\n' ]))
    __xout('XSNAPOUT', ' ', ' REGS 8-15 ', *(reg_list[8:] + [ '\n' ]))
    __xout('XSNAPOUT', '0', '\n')
    return

def __xdump(base, disp, size):
    addr_start = int(int(disp, 16) + __addr_reg(base))
    addr_end   = int(addr_start + int(size, 16))
    __xsnap_header('STORAGE')
    ctrl = '0'
    for line in Memory.dump_storage(addr_start, addr_end):
        __xout('XSNAPOUT', ctrl, line)
        ctrl = ' '
    __xout('XSNAPOUT', '0', '\n')
    return

def __xsnap_header(xdump_type):
    X_MACRO_VAR['snape_cnt'] += 1
    __xout('XSNAPOUT',
           '0', 'BEGIN XSNAP - CALL {0:>5} AT {1} USER {2}\n'.format(
            X_MACRO_VAR['snape_cnt'], SPR['PSW'].dump_hex()[1], xdump_type
            ))
    return


def __xin():
    return

def __xout(spool, *words):
    zPE.core.SPOOL.retrieve(spool).append(*words)
    return