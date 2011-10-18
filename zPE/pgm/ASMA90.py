################################################################
# Program Name:
#     ASMA90
#
# Purpose:
#     assemble the assembler source code into object code
#
# Parameter:
#     not implemented yet
#
# Input:
#     SYSIN     source code to be assembled
#     SYSLIB    macro libraries
#
# SWAP:
#     SYSUT1    required by the ASMA90 as sketch file
#
# Output:
#     SYSLIN    object module generated
#     SYSPRINT  source listing and diagnostic message
#
# Return Code:
#
# Return Value:
#     none
################################################################


import zPE

import os, sys
import re
from time import strftime

from asma90_err_code_rc import * # read recourse file for err msg

# read recourse file for objmod specification
from asma90_objmod_spec import REC_FMT as OBJMOD_REC


FILE = [ 'SYSIN', 'SYSLIB', 'SYSPRINT', 'SYSLIN', 'SYSUT1' ]

LOCAL_CONFIG = {
    'LN_P_PAGE' : 60,           # line per page for output
    }

INFO = {  # '[IWES]' : { Line_Num : [ ( Err_No, Pos_Start, Pos_End, ), ...] }
    'I' : {},           # informational messages
    'N' : {},           # notification messages
    'W' : {},           # warning messages
    'E' : {},           # error messages
    'S' : {},           # severe error messages
    }
# check __INFO() for more information

TITLE = [       # TITLE (Deck ID) list
    # ( title_string, line_num )
    ]

MNEMONIC = {
    # Line_Num : [ scope, ]                                     // type (len) 1
    # Line_Num : [ scope, LOC, ]                                // type (len) 2
    # Line_Num : [ scope, LOC, [ CONST_OBJECT, ... ], ]         // type (len) 3
    # Line_Num : [ scope,  ,  , equates, ]                      // type (len) 4
    # Line_Num : [ scope, LOC, (OBJECT_CODE), ADDR1, ADDR2, ]   // type (len) 5
    }

RELOCATE_OFFSET = {
    1 : 0,                      # { scope_id : offset }
    }

class ExternalSymbol(object):
    def __init__(self, tp, scope_id, addr, length,
                 owner, flags, alias
                 ):
        self.type = tp
        self.id = scope_id
        self.addr = addr
        self.length = length
        self.owner = owner
        self.flags = flags
        self.alias = alias

    def type_code(self):
        return {
            'SD'   : '00',
            'LD'   : '01',
            'ER'   : '02',
            'PC'   : '04',
            'CM'   : '05',
            'XD'   : '06',
            'PR'   : '06', # (another name for 'XD'?)
            'WX'   : '0A',
            'qaSD' : '0D', # Quad-aligned SD
            'qaPC' : '0E', # Quad-aligned PC
            'qaCM' : '0F', # Quad-aligned CM
            }[self.type]

ESD = {                 # External Symbol Dictionary; build during pass 1
    # 'Symbol  ' : ( ExternalSymbol(SD/PC), ExternalSymbol(ER), )
    }
ESD_ID = {              # External Symbol Dictionary ID Table
    # scope_id : 'Symbol  '
    }

class Symbol(object):
    def __init__(self, length, addr, scope_id,
                 reloc, sym_type, asm, program,
                 line_cnt, references
                 ):
        self.length     = length
        self.value      = addr
        self.id         = scope_id

        self.reloc      = reloc
        self.type       = sym_type
        self.asm        = asm
        self.program    = program

        self.defn       = line_cnt
        self.references = references
SYMBOL = {              # Cross Reference Table; build during pass 1
    # 'Symbol  ' : Symbol()
    }
SYMBOL_V = {            # Cross Reference ER Sub-Table
    # 'Symbol  ' : Symbol()
    }
SYMBOL_EQ = {           # Cross Reference =Const Sub-Table
    # 'Symbol  ' : [ Symbol(), ... ]
    }
INVALID_SYMBOL = []     # non-defined symbol
NON_REF_SYMBOL = []     # non-referenced symbol

class Using(object):
    def __init__(self, curr_addr, curr_id,
                 action,
                 using_type, lbl_addr, range_limit, lbl_id,
                 max_disp, last_stmt, lbl_text
                 ):
        self.loc_count = curr_addr
        self.loc_id = curr_id
        self.action = action
        self.u_type = using_type
        self.u_value = lbl_addr
        self.u_range = range_limit
        self.u_id = lbl_id
        self.max_disp = max_disp
        self.last_stmt = last_stmt
        self.lbl_text = lbl_text
USING_MAP = {           # Using Map
    # ( Stmt, reg, ) : Using()
    }
ACTIVE_USING = {
    # reg : Stmt
    }


def init(step):
    # check for file requirement
    if __MISSED_FILE(step) != 0:
        return zPE.RC['CRITICAL']

    rc1 = pass_1()
    rc2 = pass_2(rc1)

    __PARSE_OUT()

    return max(rc1, rc2)


def pass_1(amode = 31, rmode = 31):
    spi = zPE.core.SPOOL.retrive('SYSIN')    # input SPOOL
    spt = zPE.core.SPOOL.retrive('SYSUT1')   # sketch SPOOL

    addr = 0                    # program counter
    prev_addr = None            # previous program counter
    line_num = 0

    scope_id = 0                # current scope ID; init to None (0)
    scope_new = scope_id + 1    # next available scope ID; starting at 1
    csect_lbl = None            # current csect label

    # memory heap for constant allocation
    const_pool = {}             # same format as SYMBOL
    const_plid = None
    const_left = 0              # number of =constant LTORG/END allocated

    spi.terminate()             # manually append an EOF at the end, which
                                # will be removed before leave 1st pass

    # main read loop
    for line in spi:
        line_num += 1           # start at line No. 1

        # check EOF
        if spi.atEOF(line):
            __INFO('W', line_num, ( 140, 9, None, ))
            # replace EOF with an END instruction
            spi.unterminate()   # this indicates the generation of the END
            line = '{0:<8} END\n'.format('')
            spi.append(line)    # will be removed when encountered

        # check comment
        if line[0] == '*':
            continue

        field = zPE.resplit_sq('\s+', line[:-1], 3)

        # check for OP code
        if len(field) < 2:
            __INFO('E', line_num, ( 142, 9, None, ))

            MNEMONIC[line_num] = [ scope_id, addr, ]            # type 2
            spt.append('{0:0>5}{1:<8}\n'.format(
                    line_num, field[0]
                    ))

        # parse CSECT
        elif field[1] == 'CSECT':
            # update the CSECT info
            if scope_id:        # if not first CSECT
                ESD[csect_lbl][0].length = addr

            bad_lbl = zPE.bad_label(field[0])
            if bad_lbl == None:
                csect_lbl = '{0:<8}'.format('') # PC symbol
            elif bad_lbl:
                __INFO('E', line_num, ( 143, bad_lbl, len(field[0]), ))
                csect_lbl = '{0:<8}'.format('') # treat as PC symbol
            else:
                csect_lbl = '{0:<8}'.format(field[0])

            # parse the new CSECT
            scope_id = scope_new
            scope_new += 1      # update the next scope_id ptr
            addr = 0            # reset program counter; not fixed yet
            prev_addr = None

            if csect_lbl not in ESD:
                ESD[csect_lbl] = (
                    ExternalSymbol(
                        None, None, None, None,
                        None, None, None,
                        ),
                    ExternalSymbol(
                        None, None, None, None,
                        None, None, None,
                        ),
                    )

            if ESD[csect_lbl][0].id != None:
                # continued CSECT, switch to it
                scope_id = ESD[csect_lbl][0].id
                scope_new -= 1  # roll back the next scope id
                addr = ESD[csect_lbl][0].length
                prev_addr = None
            else:
                # new CSECT, update info
                ESD[csect_lbl][0].id = scope_id
                ESD[csect_lbl][0].addr = addr
                ESD[csect_lbl][0].flags = '00'

                ESD_ID[scope_id] = csect_lbl

                if csect_lbl == '{0:<8}'.format(''):
                    # unlabelled CSECT
                    ESD[csect_lbl][0].type = 'PC'
                else:
                    # labelled CSECT
                    ESD[csect_lbl][0].type = 'SD'

                    SYMBOL[csect_lbl] = Symbol(
                        1, addr, scope_id,
                        '', 'J', '', '',
                        line_num, []
                        )

            MNEMONIC[line_num] = [ scope_id, addr, ]            # type 2
            spt.append('{0:0>5}{1:<8} CSECT\n'.format(
                    line_num, field[0]
                    ))

        # parse USING
        elif field[1] == 'USING':
            # actual parsing in pass 2
            MNEMONIC[line_num] = [ scope_id, ]                  # type 1
            spt.append('{0:0>5}{1:<8} USING {2}\n'.format(
                    line_num , '', field[2]
                    ))

        # parse DROP
        elif field[1] == 'DROP':
            # actual parsing in pass 2
            MNEMONIC[line_num] = [ scope_id, ]                  # type 1
            spt.append('{0:0>5}{1:<8} DROP {2}\n'.format(
                    line_num , '', field[2]
                    ))

        # parse END
        elif field[1] == 'END':
            if const_plid:      # check left-over constants
                line_num_tmp = line_num - 1
                for lbl in const_pool:
                    spi.insert(line_num_tmp,
                               '{0:<14} {1}\n'.format('', lbl)
                               )
                    __ALLOC_EQ(lbl, const_pool[lbl])
                    const_left += 1
                    line_num_tmp += 1
                # close the current pool
                const_pool = {}
                const_plid = None
                # the following is to "move back" the iterator
                # need to be removed after END
                spi.insert(0, '')
                line_num -= 1
            else:               # no left-over constant, end the program
                if len(field[0]) != 0:
                    __INFO('W', line_num, ( 165, 0, None, ))

                # update the CSECT info
                ESD[csect_lbl][0].length = addr

                if len(field) == 3: # has label
                    lbl_8 = '{0:<8}'.format(field[2])
                else:               # has no label; default to 1st CSECT
                    lbl_8 = ESD_ID[1]

                addr = 0    # reset program counter
                prev_addr = None

                # check EOF again
                if spi.atEOF():
                    # no auto-generation of END, undo the termination
                    spi.unterminate()

                MNEMONIC[line_num] = [ 0, addr, ]               # type 2
                # the scope ID of END is always set to 0
                spt.append('{0:0>5}{1:<8} END   {2}\n'.format(
                        line_num, '', lbl_8
                        ))

                # remove the dummy line added in the previous branch
                if spi[0] == '':
                    spi.rmline(0)
                break           # end of program

        # parse LTORG
        elif field[1] == 'LTORG':
            # align boundary
            addr = (addr + 7) / 8 * 8

            curr_pool = [
                [],     # pool for constant with double-word alignment
                [],     # pool for constant with full-word alignment
                [],     # pool for constant with half-word alignment
                [],     # pool for constant with byte alignment
                ]
            for lbl in const_pool:
                alignment = zPE.core.asm.align_at(lbl[1])
                for i in range(0,3):
                    if alignment == 2 ** i:
                        curr_pool[3 - i].append(lbl)
                        break

            line_num_tmp = line_num
            for pool in curr_pool:
                for lbl in pool:
                    spi.insert(line_num_tmp, '{0:<15}{1}\n'.format('', lbl))
                    __ALLOC_EQ(lbl, const_pool[lbl])
                    const_left += 1
                    line_num_tmp += 1

            # close the current pool
            const_pool = {}
            const_plid = None

            MNEMONIC[line_num] = [ scope_id, addr, ]            # type 2
            spt.append('{0:0>5}{1:<8} LTORG\n'.format(line_num, ''))

        # parse EQU
        elif field[1] == 'EQU':
            if field[2].isdigit():
                # simple equates expression
                equ_reloc = 'A' # absolute symbol

                equ_addr = int(field[2]) # exp_1
                equ_len  = 1             # exp_2 [omitted, default length]
            else:
                # complex equates expression(s)
                equ_reloc = 'C' # complexly relocatable symbol

                zPE.mark4future('complex EQUates exp')

            # check label
            bad_lbl = zPE.bad_label(field[0])
            lbl_8 = '{0:<8}'.format(field[0])
            if bad_lbl == None:
                pass        # no label detected
            elif bad_lbl:
                __INFO('E', line_num, ( 143, bad_lbl, len(field[0]), ))
            elif lbl_8 in SYMBOL:
                __INFO('E', line_num, ( 43, 0, len(field[0]), ))
            else:
                SYMBOL[lbl_8] = Symbol(
                    equ_len, equ_addr, scope_id,
                    equ_reloc, 'U', '', '',
                    line_num, []
                    )

            MNEMONIC[line_num] = [ scope_id,                    # type 4
                                   None, # need info
                                   None, # need info
                                   equ_addr,
                                   ]
            spt.append('{0:0>5}{1:<8} EQU   {2}\n'.format(
                    line_num, field[0], field[2]
                    ))


        # parse DC/DS/=constant
        elif field[1] in [ 'DC', 'DS' ] or field[1][0] == '=':
            if field[1][0] == '=':
                tmp = field[1][1:]
            else:
                tmp = field[2]
            try:
                sd_info = zPE.core.asm.parse_sd(tmp)
            except:
                zPE.abort(90, 'Error: ', tmp,
                          ': Invalid constant at line {0}.\n'.format(line_num))

            # check =constant
            if field[1][0] == '=':
                if not const_left:
                    indx_s = line.index(field[1])
                    __INFO('E', line_num,
                           ( 141, indx_s, indx_s + len(field[1]), )
                           )
                    MNEMONIC[line_num] = [ scope_id, ]          # type 1
                    continue

                if field[1] in SYMBOL_EQ:
                    symbol = __HAS_EQ(field[1], scope_id)
                    if symbol == None or symbol.defn != None:
                        zPE.abort(90, 'Error: ', field[1],
                                  ': Fail to find the allocation.\n')
                    else:       # found successfully
                        const_left -= 1
                        symbol.length = sd_info[3]
                        symbol.value  = addr
                        symbol.type   = sd_info[2]
                        symbol.defn   = line_num
                else:
                    zPE.abort(90, 'Error: ', field[1],
                              ': Fail to allocate the constant.\n')

            # check address const
            if sd_info[0] == 'a' and sd_info[4] != None:
                if sd_info[2] == 'V':
                    for lbl in sd_info[4]:
                        # check external reference
                        bad_lbl = zPE.bad_label(lbl)
                        lbl_8 = '{0:<8}'.format(lbl)

                        # update the Cross-References ER Sub-Table
                        if lbl_8 not in SYMBOL_V:
                            SYMBOL_V[lbl_8] = Symbol(
                                1, 0, scope_id,
                                '', 'T', '', '',
                                line_num, [ ]
                                )
                        SYMBOL_V[lbl_8].references.append(
                            '{0:>4}{1}'.format(line_num, '')
                            )

                        # update the External Symbol Dictionary
                        if lbl_8 not in ESD:
                            ESD[lbl_8] = (
                                ExternalSymbol(
                                    None, None, None, None,
                                    None, None, None,
                                    ),
                                ExternalSymbol(
                                    None, None, None, None,
                                    None, None, None,
                                    ),
                                )
                        if ESD[lbl_8][1].id == None:
                            ESD[lbl_8][1].type = 'ER'
                            ESD[lbl_8][1].id = scope_new

                            ESD_ID[scope_new] = lbl_8
                            scope_new += 1 # update the next scope_id ptr
                elif sd_info[2] == 'A':
                    for lbl_i in range(len(sd_info[4])):
                        sd_info[4][lbl_i] = '0' # fool the paser
                    pass        # check internal reference in pass 2
                else:
                    zPE.abort(90, 'Error: ', sd_info[2],
                              ': Invalid address type.\n')

            # align boundary
            alignment = zPE.core.asm.align_at(sd_info[2])
            addr = (addr + alignment - 1) / alignment * alignment

            # check lable
            bad_lbl = zPE.bad_label(field[0])
            lbl_8 = '{0:<8}'.format(field[0])
            if bad_lbl == None:
                pass        # no label detected
            elif bad_lbl:
                __INFO('E', line_num, ( 143, bad_lbl, len(field[0]), ))
            elif lbl_8 in SYMBOL:
                __INFO('E', line_num, ( 43, 0, len(field[0]), ))
            else:
                SYMBOL[lbl_8] = Symbol(
                    sd_info[3], addr, scope_id,
                    '', sd_info[2], sd_info[2], '',
                    line_num, []
                    )

            if field[1] == 'DS':
                MNEMONIC[line_num] = [ scope_id, addr, ]        # type 2
            else:
                MNEMONIC[line_num] = [ scope_id, addr,          # type 3
                                       zPE.core.asm.get_sd(sd_info),
                                       ]
            if field[1][0] == '=':
                spt.append('{0:0>5}{1}'.format(line_num, line))
            else:
                spt.append('{0:0>5}{1:<8} {2:<5} {3}\n'.format(
                        line_num, field[0], field[1], field[2]
                        ))

            # update address
            prev_addr = addr
            addr += sd_info[1] * sd_info[3]

        # parse op-code
        elif zPE.core.asm.valid_op(field[1]):
            op_code = zPE.core.asm.get_op(field[1])
            op_len  = len(op_code)
            op_indx = zPE.core.asm.op_arg_indx(op_code)
            op_args = op_len - op_indx

            args = zPE.resplit(',', field[2], ['(',"'"], [')',"'"])

            # check arguments
            if op_args > len(args):     # too few args
                indx_s = line.index(args[-1])
                __INFO('S', line_num, ( 175, indx_s, indx_s, ))
                arg_list = field[2]
            elif op_args < len(args):   # too many args
                indx_e = line.index(field[2]) + len(field[2])
                __INFO('S', line_num, (
                        173,
                        indx_e - len(args[op_args]) - 1, # -1 for ','
                        indx_e,
                        ))
                arg_list = field[2]
            else:                       # correct number of args
                # normalize arguments
                arg_list = ''         # the final argument list
                pattern = '[,()*/+-]' # separator list
                sept = ''             # tmp separator holder
                reminder = field[2]   # tmp reminder holder

                while True:
                    # process leftover separator
                    if sept == ')':
                        # preceding argument required
                        if not last_lbl: # not offered
                            indx_e = ( line.index(field[2])
                                       + len(field[2]) # move to end of arg_list
                                       - len(reminder) # move back to error pos
                                       )
                            __INFO('E', line_num, (
                                    41, indx_e - 1, indx_e,
                                    ))
                    arg_list += sept # append leftover separator

                    # check end of arg_list
                    if reminder == '':
                        break   # end if there is no more reminder

                    # split next argument
                    res = re.search(pattern, reminder)
                    if res:
                        lbl = reminder[:res.start()]
                        sept = reminder[res.start():res.end()]
                        reminder = reminder[res.end():]
                    else:
                        lbl = reminder
                        sept = ''
                        reminder = ''
                    if lbl.count("'") % 2 == 1: # quoted literal
                        indx_s = reminder.index("'") + 1
                        if indx_s == len(reminder):
                            indx_e = indx_s
                        else:
                            indx_e = indx_s + 1
                        lbl += sept + reminder[:indx_s]
                        sept = reminder[indx_s:indx_e]
                        reminder = reminder[indx_e:]
                        if sept  and  not re.search(pattern, sept):
                            # invalid separator
                            indx_e = ( line.index(field[2])
                                       + len(field[2]) # move to end of arg_list
                                       - len(reminder) # move back to error pos
                                       )
                            __INFO('E', line_num, (
                                    41, indx_e - 1, indx_e,
                                    ))
                    parsed = False # reset the flag

                    # validate and normalize splitted argument (lbl)
                    last_lbl = lbl
                    if lbl == '':
                        continue # if no label, continue

                    if not parsed and lbl.isdigit():
                        # parse integer string
                        parsed = True # anything has only digits belongs here

                        int_val = int(lbl)
                        arg_list += "B'{0}'".format(bin(int_val)[2:])

                    if not parsed and lbl[0] == '=':
                        # parse =constant
                        parsed = True # anything started with '=' belongs here

                        if not const_plid:
                            # allocate new pool
                            const_plid = scope_id

                        if lbl in const_pool:
                            const_pool[lbl].references.append(
                                '{0:>4}{1}'.format(line_num, '')
                                )
                        elif zPE.core.asm.valid_sd(lbl[1:]):
                            const_pool[lbl] = Symbol(
                                None, None, const_plid,
                                '', lbl[1], '', '',
                                None, [
                                    '{0:>4}{1}'.format(line_num, ''),
                                    ]
                                )
                        else:
                            indx_s = line.index(lbl) + 1
                            __INFO('E', line_num,
                                   ( 65, indx_s, indx_s - 1 + len(lbl), )
                                   )
                        arg_list += lbl

                    if not parsed and zPE.core.asm.valid_sd(lbl):
                        # try parse in-line constant
                        try:
                            sd_info = zPE.core.asm.parse_sd(lbl)
                            if not sd_info[5]:
                                sd_info = (sd_info[0], sd_info[1], sd_info[2],
                                           0, sd_info[4], sd_info[3]
                                           )
                            if sd_info[2] in 'BCX': # variable length const
                                ( arg_val, arg_len ) = zPE.core.asm.value_sd(
                                    sd_info
                                    )
                                arg_list += "B'{0:0>{1}}'".format(
                                    bin(arg_val)[2:], arg_len
                                    )
                            else:
                                indx_s = line.index(lbl)
                                __INFO('E', line_num,
                                       ( 41, indx_s, indx_s - 1 + len(lbl), )
                                       )
                                arg_list += lbl
                            parsed = True
                        except:
                            pass

                    if not parsed: # get the leftover label
                        arg_list += lbl
                ## end of normalizing arguments

                # check lable
                bad_lbl = zPE.bad_label(field[0])
                lbl_8 = '{0:<8}'.format(field[0])
                if bad_lbl == None:
                    pass        # no label detected
                elif bad_lbl:
                    __INFO('E', line_num, ( 143, bad_lbl, len(field[0]), ))
                elif lbl_8 in SYMBOL:
                    __INFO('E', line_num, ( 43, 0, len(field[0]), ))
                else:
                    SYMBOL[lbl_8] = Symbol(
                        zPE.core.asm.len_op(op_code), addr, scope_id,
                        '', 'I', '', '',
                        line_num, []
                        )
            # end of checking arguments

            # parsing addr1 and addr2
            op_addr = [ 'pos 0', None, None ]
            for i in range(op_indx, op_len):
                if op_code[i].type in 'XS': # address type
                    op_addr[op_code[i].pos] = op_code[i]

            MNEMONIC[line_num] = [ scope_id, addr,              # type 5
                                   op_code, op_addr[1], op_addr[2],
                                   ]
            spt.append('{0:0>5}{1:<8} {2:<5} {3}\n'.format(
                    line_num, field[0], field[1], arg_list
                    ))

            # update address
            prev_addr = addr
            length = 0
            for code in op_code:
                length += len(code)
            if length % 2 != 0:
                zPE.abort(90, 'Error: {0}'.format(length / 2),
                          '.5: Invalid OP code length\n')
            addr += length / 2

        # unrecognized op-code
        else:
            indx_s = line.index(field[1])
            __INFO('E', line_num, ( 57, indx_s, indx_s, ))
            MNEMONIC[line_num] = [ scope_id, ]                  # type 1
            spt.append('{0:0>5}{1}'.format(line_num, line))
    # end of main read loop

    # prepare the offset look-up table of the addresses
    offset = RELOCATE_OFFSET
    for key in sorted(ESD_ID.iterkeys()):
        symbol = ESD[ESD_ID[key]][0]
        if symbol != None and symbol.id == key:
            if symbol.id == 1:  # 1st CSECT
                prev_sym = symbol
            else:               # 2nd or later CSECT
                # calculate the actual offset
                # align to double-word boundary
                offset[symbol.id] = (
                    (offset[prev_sym.id] + prev_sym.length + 7) / 8 * 8
                    )

                # update the pointer
                prev_sym = symbol

    # update the address in MNEMONIC table
    for line in spt:
        line_num = int(line[:5])                # retrive line No.
        scope_id = MNEMONIC[line_num][0]        # retrive scope ID
        if scope_id:
            if len(MNEMONIC[line_num]) in [ 2, 3, 5 ]: # type 2/3/5
                MNEMONIC[line_num][1] += RELOCATE_OFFSET[scope_id]

    # check cross references table integrality
    for (k, v) in SYMBOL.iteritems():
        if v.defn == None:
            # symbol not defined
            INVALID_SYMBOL.append(k)
    if len(INVALID_SYMBOL):
        rc_symbol = zPE.RC['ERROR']
    else:
        rc_symbol = zPE.RC['NORMAL']

    # check error messages
    if len(INFO['S']):
        rc_err = zPE.RC['SEVERE']
    elif len(INFO['E']):
        rc_err = zPE.RC['ERROR']
    elif len(INFO['W']):
        rc_err = zPE.RC['WARNING']
    elif len(INFO['N']):
        rc_err = zPE.RC['NOTIFY']
    else:
        rc_err = zPE.RC['NORMAL']

    return max(rc_symbol, rc_err)
# end of pass 1


def pass_2(rc, amode = 31, rmode = 31):
    spi = zPE.core.SPOOL.retrive('SYSIN')    # original input SPOOL
    spt = zPE.core.SPOOL.retrive('SYSUT1')   # sketch SPOOL (main input)

    addr = 0                    # program counter
    prev_addr = None            # previous program counter

    # memory heap for constant allocation
    const_pool = {}             # same format as SYMBOL
    const_plid = None

    spi.insert(0, '')           # align the line index with line No.

    # main read loop
    for line in spt:
        line_num = int(line[:5])                # retrive line No.
        line = line[5:]                         # retrive line
        scope_id = MNEMONIC[line_num][0]        # retrive scope ID
        if scope_id:
            csect_lbl = ESD_ID[scope_id]        # retrive CSECT label
            if len(MNEMONIC[line_num]) in [ 2, 3, 5 ]:
                # update & retrive address
                prev_addr = addr
                addr = MNEMONIC[line_num][1]
        else:
            csect_lbl = None

        field = zPE.resplit_sq('\s+', line[:-1], 3)

        # (skip) OP code detection
        if rc and not len(field[1]):
            if ( 142, 9, None, ) not in INFO['E'][line_num]:
                zPE.abort(92, 'Error: OP-Code detection error in pass 1.\n')
            continue            # no op code; detected in the first pass
        # skip =constant
        elif field[1][0] == '=':
            continue

        # update symbol address
        lbl_8 = '{0:<8}'.format(field[0])
        if field[0] and lbl_8 in SYMBOL:
            SYMBOL[lbl_8].value = addr

        # parse CSECT
        if field[1] == 'CSECT':
            if ( csect_lbl != '{0:<8}'.format(field[0]) and
                 csect_lbl != '{0:<8}'.format('') # in case of PC
                 ):
                zPE.abort(92, 'Error: Fail to retrive CSECT label.\n')
            if scope_id != ESD[csect_lbl][0].id:
                zPE.abort(92, 'Error: Fail to retrive scope ID.\n')

            # update symbol address
            ESD[csect_lbl][0].addr = addr


        # parse USING
        elif field[1] == 'USING':
            if len(field[0]) != 0:
                zPE.mark4future('Labeled USING')
            if len(field) < 3:
                indx_s = spi[line_num].index(field[1]) + len(field[1]) + 1
                                                                # +1 for ' '
                __INFO('S', line_num, ( 40, indx_s, None, ))
            else:
                args = zPE.resplit(',', field[2], ['(',"'"], [')',"'"])

                # check 1st argument
                sub_args = re.split(',', args[0])
                if len(sub_args) == 1:
                    # regular using
                    range_limit = 4096      # have to be 4096

                    bad_lbl = zPE.bad_label(args[0])
                    if bad_lbl == None: # nothing before ','
                        indx_s = spi[line_num].index(field[2])
                        __INFO('E', line_num,
                               ( 74, indx_s, indx_s + 1 + len(args[1]), )
                               )
                    elif bad_lbl:       # not a valid label
                        # not a relocatable address
                        indx_s = spi[line_num].index(field[2])
                        __INFO('E', line_num, ( 305, indx_s, None, ))
                    else:               # a valid label
                        lbl_8 = '{0:<8}'.format(args[0])
                        if lbl_8 in SYMBOL:
                            SYMBOL[lbl_8].references.append(
                                '{0:>4}{1}'.format(line_num, 'U')
                                )
                        else:
                            indx_s = spi[line_num].index(field[2])
                            __INFO('E', line_num,
                                   ( 44, indx_s, indx_s + 1 + len(args[1]), )
                                   )
                else:
                    if len(sub_args) != 2:
                        __INFO('S', line_num, (
                                178,
                                spi[line_num].index(sub_args[2]),
                                spi[line_num].index(args[0]) + len(args[0]) - 1,
                                ))
                    # range-limit using
                    zPE.mark4future('Range-Limited USING')

                # check existance of 2nd argument
                if len(args) < 2:
                    indx_s = spi[line_num].index(field[2]) + len(field[2])
                    __INFO('S', line_num, ( 174, indx_s, indx_s, ))

                # check following arguments
                parsed_args = [ None ] * len(args)
                for indx in range(1, len(args)):
                    reg_info = zPE.core.reg.parse_GPR(args[indx])
                    if reg_info[0] < 0:
                        indx_s = spi[line_num].index(args[indx])
                        __INFO('E', line_num,
                               ( 29, indx_s, indx_s + len(args[indx]), )
                               )
                        break
                    if reg_info[0] in parsed_args:
                        indx_s = ( spi[line_num].index(args[indx-1]) +
                                   len(args[indx-1]) + 1 # +1 for ','
                                   )
                        __INFO('E', line_num,
                               ( 308, indx_s, indx_s + len(args[indx]), )
                               )
                        break
                    # register OK, record it
                    parsed_args[indx] = reg_info[0]
                    if reg_info[1]:
                        # a reference to a symbol
                        reg_info[1].references.append(
                            '{0:>4}{1}'.format(line_num, 'U')
                            )

            if not __INFO_GE(line_num, 'E'):
                # update using map
                USING_MAP[line_num, parsed_args[1]] = Using(
                    addr, scope_id,
                    'USING',
                    'ORDINARY', SYMBOL[lbl_8].value,
                    range_limit, SYMBOL[lbl_8].id,
                    0, '{0:>5}'.format(''), field[2]
                    )
                ACTIVE_USING[parsed_args[1]] = line_num # start domain of USING

                for indx in range(2, len(args)):
                    USING_MAP[line_num, parsed_args[indx]] = Using(
                        addr, scope_id,
                        'USING',
                        'ORDINARY', SYMBOL[lbl_8].value + 4096 * (indx - 1),
                        range_limit, SYMBOL[lbl_8].id,
                        0, '{0:>5}'.format(''), ''
                        )
                    ACTIVE_USING[parsed_args[indx]] = line_num


        # parse DROP
        elif field[1] == 'DROP':
            # update using map
            args = zPE.resplit(',', field[2], ['(',"'"], [')',"'"])
            for indx in range(len(args)):
                reg_info = zPE.core.reg.parse_GPR(args[indx])
                if reg_info[0] < 0:
                    indx_s = spi[line_num].index(args[indx])
                    __INFO('E', line_num,
                           ( 29, indx_s, indx_s + len(args[indx]), )
                           )
                    continue
                if reg_info[0] in ACTIVE_USING:
                    del ACTIVE_USING[reg_info[0]] # end domain of USING
                    if reg_info[1]:
                        # a reference to a symbol
                        reg_info[1].references.append(
                            '{0:>4}{1}'.format(line_num, 'D')
                            )
                else:
                    indx_s = spi[line_num].index(args[indx])
                    __INFO('W', line_num,
                           ( 45, indx_s, indx_s + len(args[indx]), )
                           )


        # parse END
        elif field[1] == 'END':
            lbl_8 = '{0:<8}'.format(field[2])
            if lbl_8 in SYMBOL:
                SYMBOL[lbl_8].references.append(
                    '{0:>4}{1}'.format(line_num, '')
                    )
            else:
                indx_s = spi[line_num].index(field[2])
                __INFO('E', line_num, ( 44, indx_s, indx_s + len(field[2]), ))
            # update using map
            ACTIVE_USING.clear() # end domain of all USINGs


        # skip any line that do not need second pass
        elif field[1] in [ 'LTORG', 'EQU', ]:
            pass


        # parse DC/DS
        elif field[1] in [ 'DC', 'DS' ]:
            try:
                sd_info = zPE.core.asm.parse_sd(field[2])
            except:
                zPE.abort(90,'Error: {0}: Invalid constant.\n'.format(field[2]))

            # check address const
            if sd_info[0] == 'a' and sd_info[4] != None:
                # check internal reference
                if sd_info[2] == 'A':
                    for lbl_i in range(len(sd_info[4])):
                        # for each 'SYMBOL', try to resolve an address
                        lbl = sd_info[4][lbl_i]
                        sd_info[4][lbl_i] = '0'

                        res = __PARSE_ARG(lbl)

                        if isinstance(res, int):
                            indx_s = spi[line_num].index(lbl)
                            __INFO('S', line_num,
                                   ( 35, indx_s + res, indx_s + len(lbl), )
                                   )
                            break

                        reloc_cnt = 0    # number of relocatable symbol
                        reloc_arg = None # backup of the relocatable symbol
                        for indx in range(len(res[0])):
                            # for each element in the exp, try to envaluate

                            if reloc_cnt > 1: # more than one relocatable symbol
                                indx_s = spi[line_num].index(lbl)
                                __INFO('E', line_num,
                                       ( 78, indx_s, indx_s + len(lbl), )
                                       )
                                break
                            if res[1][indx] == 'eq_constant':
                                indx_s = spi[line_num].index(res[0][indx])
                                __INFO('E', line_num, (
                                        30,
                                        indx_s,
                                        indx_s + len(res[0][indx]),
                                        ))
                                break

                            if ( res[1][indx] == 'location_ptr' or
                                 res[1][indx] == 'valid_symbol'
                                 ):
                                if res[1][indx] == 'location_ptr':
                                    pass # no special process required
                                else:
                                    bad_lbl = zPE.bad_label(res[0][indx])
                                    lbl_8 = '{0:<8}'.format(res[0][indx])

                                    if bad_lbl:
                                        indx_s = spi[line_num].index(
                                            res[0][indx]
                                            )
                                        __INFO('E', line_num, (
                                                74,
                                                indx_s,
                                                indx_s + len(res[0][indx]),
                                                ))
                                    elif lbl_8 not in SYMBOL:
                                        indx_s = spi[line_num].index(
                                            res[0][indx]
                                            )
                                        __INFO('E', line_num, (
                                                44,
                                                indx_s,
                                                indx_s + len(res[0][indx]),
                                                ))
                                # check complex addressing
                                if ( ( indx-1 >= 0  and
                                       res[0][indx-1] in '*/()'
                                       ) or
                                     ( indx+1 < len(res[0])  and
                                       res[0][indx+1] in '*/()'
                                       ) ):
                                    indx_s = spi[line_num].index(lbl)
                                    __INFO('E', line_num, (
                                            32,
                                            indx_s,
                                            indx_s + len(lbl),
                                            ))
                                    break
                                reloc_arg = res[0][indx]
                                res[0][indx] = '0'
                                reloc_cnt += 1
                            elif res[1][indx] == 'inline_const':
                                tmp = zPE.core.asm.parse_sd(res[0][indx])
                                if tmp[2] not in 'BCX': # variable length const
                                    indx_s = spi[line_num].index(
                                        res[0][indx]
                                        )
                                    __INFO('E', line_num, (
                                            41,
                                            indx_s,
                                            indx_s + len(res[0][indx]),
                                            )
                                           )
                                    break
                                elif res[0][indx][0] != tmp[2]: # e.g. 2B'10'
                                    indx_s = spi[line_num].index(
                                        res[0][indx]
                                        )
                                    __INFO('E', line_num, (
                                            145,
                                            indx_s,
                                            indx_s + len(res[0][indx]),
                                            ))
                                    break
                                elif res[0][indx][1] != "'": # e.g. BL2'1'
                                    indx_s = spi[line_num].index(
                                        res[0][indx]
                                        )
                                    __INFO('E', line_num, (
                                            150,
                                            indx_s,
                                            indx_s + len(res[0][indx]),
                                            ))
                                    break
                                # parse inline constant, length check required
                                try:
                                    sd = zPE.core.asm.get_sd(tmp)[0]
                                    parsed_addr = zPE.core.asm.X_.tr(sd.dump())
                                    if len(parsed_addr) <= len(
                                        re.split('[xL]', hex(2 ** amode - 1))[1]
                                        ):
                                        res[0][indx] = str(int(parsed_addr, 16))
                                    else:
                                        indx_s = spi[line_num].index(
                                            res[0][indx]
                                            )
                                        __INFO('E', line_num, (
                                                146,
                                                indx_s,
                                                indx_s + len(res[0][indx]),
                                                ))
                                except:
                                    zPE.abort(
                                        92, 'Error: ', res[0][indx],
                                        ': Fail to parse the expression.\n'
                                              )
                        # end of processing res

                        if __INFO_GE(line_num, 'E'):
                            break # if has error, stop processing

                        # calculate constant part
                        if reloc_cnt < 2:
                            try:
                                ex_disp = eval(''.join(res[0]))
                            except:
                                zPE.abort(92, 'Error: ', ''.join(res[0]),
                                          ': Invalid expression.\n')
                        # evaluate expression
                        if reloc_cnt == 0:      # no relocatable symbol
                            sd_info[4][lbl_i] = str(ex_disp)
                        elif reloc_cnt == 1:    # one relocatable symbol
                            if reloc_arg == '*':
                                lbl_8 = '*{0}'.format(line_num)
                            else:
                                lbl_8 = '{0:<8}'.format(reloc_arg)

                            if __IS_ADDRESSABLE(lbl_8, csect_lbl, ex_disp):
                                # update Using Map
                                addr_res = __ADDRESSING(
                                    lbl_8, csect_lbl, ex_disp
                                    )
                                using = USING_MAP[addr_res[1]]
                                using.max_disp = max(
                                    using.max_disp, addr_res[0]
                                    )
                                using.last_stmt = '{0:>5}'.format(line_num)
                                # update CR table
                                if reloc_arg != '*':
                                    SYMBOL[lbl_8].references.append(
                                        '{0:>4}{1}'.format(line_num, '')
                                        )
                                sd_info[4][lbl_i] = str(
                                    using.u_value + addr_res[0]
                                    )
                            else:
                                indx_s = spi[line_num].index(lbl)
                                __INFO('E', line_num,
                                       ( 34, indx_s, indx_s + len(lbl), )
                                       )
                    # end of processing args

                    # update the constant information
                    if not __INFO_GE(line_num, 'E'):
                        zPE.core.asm.update_sd(MNEMONIC[line_num][2], sd_info)

        # parse op-code
        elif zPE.core.asm.valid_op(field[1]):
            op_code = MNEMONIC[line_num][2]
            op_indx = zPE.core.asm.op_arg_indx(op_code)
            op_args = len(op_code) - op_indx

            args = zPE.resplit(',', field[2], ['(',"'"], [')',"'"])

            if op_args != len(args):
                continue        # should be processed in pass 1

            p1_field = zPE.resplit_sq('\s+', spi[line_num], 3)
            p1_args = zPE.resplit(',', p1_field[2], ['(',"'"], [')',"'"])

            # check reference
            for lbl_i in range(len(args)):
                if __INFO_GE(line_num, 'E'): # could be flagged in pass 1
                    break # if has error, stop processing args
                abs_values = False # assume no absolute values

                lbl = args[lbl_i]
                p1_lbl = p1_args[lbl_i]

                res = __IS_ABS_ADDR(lbl)
                if op_code[lbl_i + op_indx].type in 'XS' and res != None:
                    # absolute address found
                    abs_values = True

                    # check length
                    if len(res[0][2:-1]) > 12: # B'<12 bit displacement>'
                        indx_s = spi[line_num].index(p1_lbl)
                        if '(' in p1_lbl:
                            tmp = p1_lbl.index('(')
                        else:
                            tmp = len(p1_lbl)
                        __INFO('E', line_num,
                               ( 28, indx_s, indx_s + tmp, )
                               )
                        break   # stop processing current res
                    res[0] = zPE.core.asm.value_sd(
                        zPE.core.asm.parse_sd(res[0])
                        )[0]    # convert displacement back to int

                    # validate registers
                    if op_code[lbl_i + op_indx].type in 'S':
                        if ',' in p1_lbl:
                            indx_s = spi[line_num].index(p1_lbl)
                            __INFO('S', line_num, (
                                179,
                                indx_s + p1_lbl.index(','),
                                indx_s + len(p1_lbl) + 1,
                                ))
                            break   # stop processing current res
                        indx_range = [ 1 ]
                        del res[2] # remove the extra item (fake base)
                        indx_os = [
                            None,
                            ( p1_lbl.index('('), p1_lbl.index(')') ),
                            ]
                    elif ',' in p1_lbl:
                        indx_range = [ 1, 2 ]
                        indx_os = [ # index offset for error msg generation
                            None,
                            ( p1_lbl.index('('), p1_lbl.index(',') ),
                            ( p1_lbl.index(','), p1_lbl.index(')') ),
                            ]
                    else:
                        indx_range = [ 1, 2 ]
                        indx_os = [
                            None,
                            ( p1_lbl.index('('), p1_lbl.index(')') ),
                            None, # no base offered
                            ]
                    for i in indx_range:
                        # validate register
                        reg_info = zPE.core.reg.parse_GPR(res[i])
                        if reg_info[0] >= 0:
                            res[i] = reg_info[0]
                            if reg_info[1]:
                                reg_info[1].references.append(
                                    '{0:>4}{1}'.format(line_num, '')
                                    )
                        else:
                            indx_s = spi[line_num].index(p1_lbl) + 1
                            __INFO('E', line_num,
                                   ( 29,
                                     indx_s + indx_os[i][0],
                                     indx_s + indx_os[i][1],
                                     )
                                   )
                            break   # stop processing current res

                elif op_code[lbl_i + op_indx].type in 'R':
                    # register found
                    abs_values = True

                    res = [ lbl ]
                    if lbl.startswith("B'"):
                        res[0] = __REDUCE_EXP(lbl)
                        if res[0] == None: # label cannot be reduced
                            res[0] = lbl
                        else:
                            try:
                                res[0] = zPE.core.asm.value_sd(
                                    zPE.core.asm.parse_sd(res[0])
                                    )[0]
                            except: # cannot evaluate B-const
                                res[0] = lbl
                    # validate register
                    reg_info = zPE.core.reg.parse_GPR(res[0])
                    if reg_info[0] >= 0:
                        res[0] = reg_info[0]
                        if reg_info[1]:
                            reg_info[1].references.append(
                                '{0:>4}{1}'.format(
                                    line_num,
                                    op_code[lbl_i + op_indx].flag()
                                    )
                                )
                    else:
                        indx_s = spi[line_num].index(p1_lbl) + 1
                        __INFO('E', line_num,
                               ( 29, indx_s, indx_s + len(p1_lbl), )
                               )
                        break   # stop processing current res
                else:
                    res    = __PARSE_ARG(lbl)
                    p1_res = __PARSE_ARG(p1_lbl)

                    if isinstance(res, int):
                        # delimiter error, S035, S173-175, S178-179
                        indx_s = spi[line_num].index(p1_args[lbl_i])
                        if spi[line_num][indx_s + p1_res - 1] in ')':
                            if lbl_i + op_indx < op_args:
                                err_num = 175 # expect comma
                            else:
                                err_num = 173 # expect blank
                        else:
                            err_num = 35 # cannot determine
                        __INFO('S', line_num, (
                                err_num,
                                indx_s + p1_res,
                                indx_s + len(p1_args[lbl_i]),
                                ))
                        break   # stop processing current res

                    reloc_cnt = 0    # number of relocatable symbol
                    reloc_arg = None # backup of the relocatable symbol
                    for indx in range(len(res[0])):
                        # for each element in the exp, try to envaluate
                        if reloc_cnt > 1: # more than one relocatable symbol
                            indx_s = spi[line_num].index(lbl)
                            __INFO('E', line_num,
                                   ( 78, indx_s, indx_s + len(lbl), )
                                   )
                            break   # stop processing current res

                        if ( res[1][indx] == 'eq_constant'  or
                             res[1][indx] == 'location_ptr' or
                             res[1][indx] == 'valid_symbol'
                             ):
                            if res[1][indx] == 'eq_constant':
                                if op_code[lbl_i + op_indx].for_write:
                                    indx_s = spi[line_num].index(res[0][indx])
                                    __INFO('E', line_num, (
                                            30,
                                            indx_s,
                                            indx_s + len(res[0][indx]),
                                            ))
                                    break   # stop processing current res

                                tmp = zPE.resplit_sq('[()]', lbl)
                                symbol = __HAS_EQ(tmp[0], scope_id)

                                if len(tmp) > 1 and indx != len(res[0]) - 1:
                                    indx_s = (
                                        spi[line_num].index(p1_res[0][indx]) +
                                        len(p1_res[0][indx])
                                        )
                                    indx_e = (
                                        spi[line_num].index(p1_lbl) +
                                        len(p1_lbl)
                                        )
                                    __INFO('S', line_num,
                                           ( 173, indx_s, indx_e, )
                                           )
                                    break   # stop processing current res
                                elif symbol == None:
                                    if not __INFO_GE(line_num, 'E'):
                                        zPE.abort(90, 'Error: ', p1_lbl,
                                                  ': symbol not in EQ table.\n')
                                elif symbol.defn == None:
                                    zPE.abort(90, 'Error: ', p1_lbl,
                                              ': symbol not allocated.\n')
                            elif res[1][indx] == 'location_ptr':
                                pass # no special process required
                            else: # valid_symbol
                                tmp = zPE.resplit_sq('[()]', res[0][indx])
                                bad_lbl = zPE.bad_label(tmp[0])
                                lbl_8 = '{0:<8}'.format(tmp[0])

                                if ( len(tmp) > 1 and
                                     op_code[lbl_i + op_indx].type in 'S'
                                     ):
                                    indx_s = spi[line_num].index(p1_lbl)
                                    __INFO('S', line_num, (
                                        173,
                                        indx_s + p1_lbl.index('('),
                                        indx_s + len(p1_lbl) + 1,
                                        ))
                                    break   # stop processing current res
                                elif len(tmp) > 1 and indx != len(res[0]) - 1:
                                    # complex symbol must be last node of exp
                                    indx_s = (
                                        spi[line_num].index(p1_res[0][indx]) +
                                        len(p1_res[0][indx])
                                        )
                                    indx_e = (
                                        spi[line_num].index(p1_lbl) +
                                        len(p1_lbl)
                                        )
                                    __INFO('S', line_num,
                                           ( 173, indx_s, indx_e, )
                                           )
                                    break   # stop processing current res
                                elif bad_lbl:
                                    indx_s = (
                                        spi[line_num].index(p1_res[0][indx])
                                        )
                                    __INFO('E', line_num, (
                                            74,
                                            indx_s,
                                            indx_s + len(p1_res[0][indx]),
                                            ))
                                    break   # stop processing current res
                                elif lbl_8 not in SYMBOL:
                                    indx_s = (
                                        spi[line_num].index(p1_res[0][indx])
                                        )
                                    __INFO('E', line_num, (
                                            44,
                                            indx_s,
                                            indx_s + len(p1_res[0][indx]),
                                            ))
                                    break   # stop processing current res
                            # check complex addressing
                            if ( ( indx-1 >= 0  and
                                   res[0][indx-1] in '*/()'
                                   ) or
                                 ( indx+1 < len(res[0])  and
                                   res[0][indx+1] in '*/()'
                                   ) ):
                                indx_s = spi[line_num].index(p1_lbl)
                                __INFO('E', line_num, (
                                        32,
                                        indx_s,
                                        indx_s + len(p1_lbl),
                                        ))
                                break   # stop processing current res
                            reloc_arg = res[0][indx]
                            res[0][indx] = "B'0'"
                            reloc_cnt += 1
                        elif res[1][indx] == 'inline_const':
                            sd_info = zPE.core.asm.parse_sd(res[0][indx])
                            if res[0][indx][0] != sd_info[2]: # e.g. 2B'10'
                                indx_s = (
                                    spi[line_num].index(p1_res[0][indx])
                                    )
                                __INFO('E', line_num, (
                                        145,
                                        indx_s,
                                        indx_s + len(p1_res[0][indx]),
                                        ))
                                break   # stop processing current res
                            elif res[0][indx][1] != "'": # e.g. BL2'1'
                                indx_s = (
                                    spi[line_num].index(p1_res[0][indx])
                                    )
                                __INFO('E', line_num, (
                                        150,
                                        indx_s,
                                        indx_s + len(p1_res[0][indx]),
                                        ))
                                break   # stop processing current res

                            if not sd_info[5]:
                                sd_info = (sd_info[0], sd_info[1], sd_info[2],
                                           0, sd_info[4], sd_info[3]
                                           )
                            (arg_val, arg_len) = zPE.core.asm.value_sd(sd_info)

                            res[0][indx] = "B'{0:0>{1}}'".format(
                                bin(arg_val)[2:], arg_len
                                )
                # end of processing res
                if __INFO_GE(line_num, 'E'):
                    break # if has error, stop processing args

                # calculate constant part
                if not abs_values and reloc_cnt < 2:
                    ex_disp = __REDUCE_EXP(''.join(res[0]))
                    if ex_disp == None:
                        zPE.abort(92, 'Error: ', ''.join(res[0]),
                                  ': Invalid expression.\n')
                    sd_info = zPE.core.asm.parse_sd(ex_disp)
                    sd_info = (sd_info[0], sd_info[1], sd_info[2],
                               0, sd_info[4], sd_info[3]
                               ) # all are auto-generated, no 'L' at all
                    (ex_disp, dummy) = zPE.core.asm.value_sd(sd_info)
                    if not op_code[lbl_i + op_indx].is_aligned(ex_disp):
                        indx_s = spi[line_num].index(p1_lbl)
                        __INFO('I', line_num,
                               ( 33, indx_s, indx_s + len(p1_lbl), )
                               )

                # evaluate expression
                if abs_values:    # absolute values
                    op_code[lbl_i + op_indx].set(*res)
                elif reloc_cnt == 0:    # no relocatable symbol
                    try:
                        op_code[lbl_i + op_indx].set(ex_disp)
                    except:
                        indx_s = spi[line_num].index(p1_lbl)
                        __INFO('E', line_num,
                               ( 29, indx_s, indx_s + len(p1_lbl), )
                               )
                elif reloc_cnt == 1:    # one relocatable symbol
                    if reloc_arg == '*':
                        # current location ptr
                        lbl_8 = '*{0}'.format(line_num)
                        reg_indx = '0'
                    else:
                        # label
                        tmp = zPE.resplit_sq('[()]', reloc_arg)
                        if reloc_arg[0] == '=':
                            lbl_8 = tmp[0]
                        else:
                            lbl_8 = '{0:<8}'.format(tmp[0])
                        if len(tmp) > 1:
                            # [ symbol, indx, '' ]
                            sd_info = zPE.core.asm.parse_sd(tmp[1])
                            sd_info = (sd_info[0], sd_info[1], sd_info[2],
                                       0, sd_info[4], sd_info[3]
                                       ) # all are auto-generated, no 'L' at all
                            (reg_indx, dummy) = zPE.core.asm.value_sd(sd_info)
                            reg_indx = str(reg_indx)
                        else:
                            # [ symbol ]
                            reg_indx = '0'

                    if __IS_ADDRESSABLE(lbl_8, csect_lbl, ex_disp):
                        # update Using Map
                        addr_res = __ADDRESSING(
                            lbl_8, csect_lbl, ex_disp
                            )
                        using = USING_MAP[addr_res[1]]
                        using.max_disp = max(
                            using.max_disp, addr_res[0]
                            )
                        using.last_stmt = '{0:>5}'.format(line_num)
                        # update CR table
                        if reloc_arg == '*':
                            pass # no reference of any symbol
                        else:
                            if reloc_arg[0] == '=':
                                symbol = __HAS_EQ(lbl_8, scope_id)
                            else:
                                symbol = SYMBOL[lbl_8]
                            symbol.references.append(
                                '{0:>4}{1}'.format(
                                    line_num,
                                    op_code[lbl_i + op_indx].flag()
                                    )
                                )
                        if op_code[lbl_i + op_indx].type in 'S':
                            op_code[lbl_i + op_indx].set(
                                addr_res[0], addr_res[2]
                                )
                        else:
                            op_code[lbl_i + op_indx].set(
                                addr_res[0], int(reg_indx), addr_res[2]
                                )
                    else:
                        indx_s = spi[line_num].index(p1_lbl)
                        __INFO('E', line_num,
                               ( 34, indx_s, indx_s + len(p1_lbl), )
                               )
            # end of processing args

        # unrecognized op-code
        else:
            pass # mark; flag error here
    # end of main read loop

    spi.rmline(0)               # undo the align of line No.


    # check cross references table integrality
    for (k, v) in SYMBOL.iteritems():
        if len(v.references) == 0:
            # symbol not referenced
            NON_REF_SYMBOL.append((v.defn, k, ))


    # check error messages
    if len(INFO['S']):
        rc_err = zPE.RC['SEVERE']
    elif len(INFO['E']):
        rc_err = zPE.RC['ERROR']
    elif len(INFO['W']):
        rc_err = zPE.RC['WARNING']
    elif len(INFO['N']):
        rc_err = zPE.RC['NOTIFY']
    else:
        rc_err = zPE.RC['NORMAL']

    # generate object module if no error occured
    if rc_err <= zPE.RC['WARNING']:
        rc_err = max(rc_err, obj_mod_gen(amode, rmode))

    return rc_err


def obj_mod_gen(amode, rmode):
    spo = zPE.core.SPOOL.retrive('SYSLIN')   # output SPOOL (object module)

    # prepare variable field
    variable_field = []
    for key in sorted(ESD_ID.iterkeys()):
        k = ESD_ID[key]
        if ESD[k][0] and ESD[k][0].id == key:
            v = ESD[k][0]
        else:
            v = ESD[k][1]
        variable_field.append([ k, v ])
    # prepare title
    if TITLE:
        title = TITLE[0][0]
    else:
        title = ''

    # generate ESD records
    last_group_indx = len(variable_field) / 3
    for i in range(last_group_indx): # for every 3 variable fields
        spo.append(OBJMOD_REC['ESD'](
                variable_field[i * 3 : (i+1) * 3],
                amode, rmode,
                title, len(spo) + 1
                ))
    spo.append(OBJMOD_REC['ESD'](
            variable_field[last_group_indx : ],
            amode, rmode,
            title, len(spo) + 1
            ))

    return zPE.RC['NORMAL']


### Supporting Functions
def __ADDRESSING(lbl, csect_lbl, ex_disp = 0):
    rv = [ 4096, None, -1, ]  # init to least priority USING (non-exsit)
    eq_const = __HAS_EQ(lbl, ESD[csect_lbl][0].id)

    for (k, v) in ACTIVE_USING.iteritems():
        if __IS_IN_RANGE(lbl, ex_disp, USING_MAP[v,k], ESD[csect_lbl][0]):
            if lbl[0] == '*':
                disp = MNEMONIC[ int( lbl[1:] ) ][1] - USING_MAP[v,k].u_value
            elif lbl[0] == '=':
                disp = MNEMONIC[ eq_const.defn  ][1] - USING_MAP[v,k].u_value
            else:
                disp = MNEMONIC[SYMBOL[lbl].defn][1] - USING_MAP[v,k].u_value
            disp += ex_disp
            if ( ( disp < rv[0] )  or           # minimal displacement rule
                 ( disp == rv[0] and k > rv[2]) # maximal register rule
                 ):
                rv = [ disp, (v, k), k, ]
    return rv

def __ALLOC_EQ(lbl, symbol):
    if lbl not in SYMBOL_EQ:
        SYMBOL_EQ[lbl] = []
    SYMBOL_EQ[lbl].append(symbol) # mark =const as allocable

def __HAS_EQ(lbl, scope_id):
    if lbl not in SYMBOL_EQ:
        return None
    for symbol in SYMBOL_EQ[lbl]:
        if symbol.id == scope_id:
            return symbol
    return None                 # nor found

def __IS_ADDRESSABLE(lbl, csect_lbl, ex_disp = 0):
    if (lbl[0] != '*') and (lbl not in SYMBOL) and (lbl not in SYMBOL_EQ):
        return False            # not an *, a symbol, nor a =constant
    if len(ACTIVE_USING) == 0:
        return False            # not in domain of any USING
    for (k, v) in ACTIVE_USING.iteritems():
        if __IS_IN_RANGE(lbl, ex_disp, USING_MAP[v,k], ESD[csect_lbl][0]):
            return True
    return False                # not in the range of any USING

# rv:
#   [ disp_B_const, indx_num, base_num ]
#   None    if error happened during parsing
#
# Note: no length check nor register validating involved
def __IS_ABS_ADDR(addr_arg):
    reminder = addr_arg

    # parse displacement
    res = re.search('\(', reminder)
    if res != None:     # search succeed
        disp     = reminder[:res.start()]
        reminder = reminder[res.end():]
    else:
        disp     = reminder
        reminder = ''
    disp = __REDUCE_EXP(disp)
    if disp == None:            # disp cannot be reduced
        return None

    # parse index
    res = re.search('[,)]', reminder)
    if res != None:     # search succeed
        matched_ch = reminder[res.start():res.end()]

        indx = reminder[:res.start()]
        reminder = reminder[res.end():]
        if not indx:
            if matched_ch == ',': # omitted indx
                indx = '0'
            else:                 # nothing in parenthesis
                return None
    else:
        indx = '0'
    # check B-const
    if indx.startswith("B'"):
        indx = __REDUCE_EXP(indx)
        if indx == None:        # indx cannot be reduced
            return None
        try:
            indx = zPE.core.asm.value_sd(
                zPE.core.asm.parse_sd(indx)
                )[0]
        except:                 # cannot evaluate B-const
            return None

    # parse base
    res = re.search('\)', reminder)
    if res != None:     # search succeed
        base     = reminder[:res.start()]
        reminder = reminder[res.end():]
        if not base:
            base = '0'
    else:
        base = '0'
    # check B-const
    if base.startswith("B'"):
        base = __REDUCE_EXP(base)
        if base == None:        # base cannot be reduced
            return None
        try:
            base = zPE.core.asm.value_sd(
                zPE.core.asm.parse_sd(base)
                )[0]
        except:                 # cannot evaluate B-const
            return None

    # check reminder
    if reminder != '':
        return None
    return [ disp, indx, base ]

def __IS_IN_RANGE(lbl, ex_disp, using, csect):
    u_range = min(
        using.u_value + using.u_range, # ending addr of the USING
        csect.addr + csect.length      # ending addr of the CSECT
        )
    eq_const = __HAS_EQ(lbl, csect.id)

    if ( ( (lbl[0] == '*')              and # is loc_ptr
           (int(lbl[1:]) + ex_disp < u_range)
           )  or
         ( (lbl[0] == '=')              and # is =constant
           (MNEMONIC[eq_const.defn][1] + ex_disp < u_range)
           )  or
         ( (SYMBOL[lbl].type != 'U')    and # is symbol
           (MNEMONIC[SYMBOL[lbl].defn][1] + ex_disp < u_range)
           )):
        return True
    else:
        return False

def __INFO(err_level, line, item):
    if line not in INFO[err_level]:
        INFO[err_level][line] = []
    INFO[err_level][line].append(item)

def __INFO_GE(line_num, err_level):
    if line_num in INFO['S']:
        return True
    if err_level == 'S':        # >= S, ignore E,W,N,I
        return False
    if line_num in INFO['E']:
        return True
    if err_level == 'E':        # >= E, ignore W,N,I
        return False
    if line_num in INFO['W']:
        return True
    if err_level == 'W':        # >= W, ignore N,I
        return False
    if line_num in INFO['N']:
        return True
    if err_level == 'N':        # >= N, ignore I
        return False
    if line_num in INFO['I']:
        return True
    return False                # >= I

def __MISSED_FILE(step):
    sp1 = zPE.core.SPOOL.retrive('JESMSGLG') # SPOOL No. 01
    sp3 = zPE.core.SPOOL.retrive('JESYSMSG') # SPOOL No. 03
    ctrl = ' '

    cnt = 0
    for fn in FILE:
        if fn not in zPE.core.SPOOL.list():
            sp1.append(ctrl, strftime('%H.%M.%S '), zPE.JCL['jobid'],
                       '  IEC130I {0:<8}'.format(fn),
                       ' DD STATEMENT MISSING\n')
            sp3.append(ctrl, 'IEC130I {0:<8}'.format(fn),
                       ' DD STATEMENT MISSING\n')
            cnt += 1

    return cnt


# rv: ( [ symbol_1, ... ], [ desc_1, ... ], )
# or  err_indx  if error occurs
def __PARSE_ARG(arg_str):
    parts = []                  # components of the expression
    descs = []                  # descriptions of the components
    reminder = arg_str

    while True:
        if reminder[0] == '(':  # start of a sub-expression
            parts.append('(')
            descs.append('parenthesis')
            reminder = reminder[1:]

        if reminder[0] == '*':  # current location ptr
            parts.append('*')
            descs.append('location_ptr')
            reminder = reminder[1:]
        else:                   # number / symbol
            res = zPE.resplit_sq('[*/+-]', reminder)[0]

            bad_lbl = zPE.bad_label(zPE.resplit_sq('\(', res)[0])
            if bad_lbl:
                try:
                    sd_info = zPE.core.asm.parse_sd(res)
                except:         # not a constant
                    sd_info = None

                if res.isdigit(): # pure number
                    parts.append(res)
                    descs.append('regular_num')
                elif len(zPE.resplit_sq('\)', res)) > 1: # abs addr + something
                    return res.index(')') + 1
                elif sd_info:   # inline constant
                    try:
                        if sd_info[0] == 'a':
                            raise TypeError
                        zPE.core.asm.get_sd(sd_info)
                        parts.append(res)
                        descs.append('inline_const')
                    except:     # invalid constant; return err pos
                        return len(arg_str) - len(reminder)
                elif res[0] == '=': # =constant
                    tmp = zPE.resplit_sq('\(', res)
                    if len(tmp) > 1 and not re.match('\d{1,2}\)', tmp[1]):
                        return ( len(arg_str) - len(reminder) +
                                 len(zPE.resplit_sq(',', res)[0]) )
                    parts.append(res)
                    descs.append('eq_constant')
                else:           # invalid operand; return err pos
                    return len(arg_str) - len(reminder)
            else:
                tmp = zPE.resplit_sq('\(', res) # search for '('
                arg_lbl = tmp[0]
                if len(tmp) > 1: # has '('
                    tmp = zPE.resplit_sq(',', tmp[1]) # search for ','
                    if len(tmp) > 1: # has ','
                        return ( len(arg_str) - len(reminder) +
                                 len(zPE.resplit_sq(',', res)[0])
                                 )
                    tmp = zPE.resplit_sq('\)', tmp[0]) # search for ')'
                    arg_val = tmp[0]
                    if not arg_val:                   # no value
                        return ( len(arg_str) - len(reminder) +
                                 len(zPE.resplit_sq('\(', res)[0])
                                 )
                    if len(tmp) != 2 or tmp[1] != '': # not end with ')'
                        return ( len(arg_str) - len(reminder) +
                                 len(zPE.resplit_sq('\)', res)[0])
                                 )
                    # try to reduce the value
                    tmp = __REDUCE_EXP(arg_val)
                    if tmp == None:
                        try:
                            tmp = eval(arg_val)
                        except:
                            return ( len(arg_str) - len(reminder) +
                                     len(zPE.resplit_sq('\(', res)[0])
                                     ) # cannot reduce
                    res = '{0}({1})'.format(arg_lbl, tmp)
                parts.append(res)
                descs.append('valid_symbol')
            reminder = reminder[len(res):]

        if len(reminder) and reminder[0] == ')': # start of a sub-expression
            parts.append(')')
            descs.append('parenthesis')
            reminder = reminder[1:]

        if len(reminder):       # operator
            if reminder[0] not in '*/+-': # invalid operator; return err pos
                return len(arg_str) - len(reminder)
            parts.append(reminder[0])
            descs.append('operator')
            reminder = reminder[1:]
        else:                   # no more, stop
            break

    return ( parts, descs, )


def __PARSE_OUT():
    spi = zPE.core.SPOOL.retrive('SYSIN')    # input SPOOL
    spt = zPE.core.SPOOL.retrive('SYSUT1')   # sketch SPOOL
    spo = zPE.core.SPOOL.retrive('SYSPRINT') # output SPOOL

    pln_cnt = 0                 # printed line counter of the current page
    page_cnt = 1                # page counter

    ### header portion of the report
    ctrl = '1'
    spo.append(ctrl, '{0:>40} High Level Assembler Option Summary                   (PTF UK28644)   Page {1:>4}\n'.format(' ', 1))
    ctrl = '-'
    spo.append(ctrl, '{0:>90}  HLASM R5.0  {1}\n'.format(
            ' ', strftime('%Y/%m/%d %H.%M')
            ))
    pln_cnt += 2
    ctrl = '0'


    ### main read loop, op code portion of the report
    ### end of main read loop


    ### summary portion of the report



# note: work only for B-const
def __REDUCE_EXP(exp):
    if exp == '':
        return "B'0'"

    exp_list = []
    sd_len = None               # tmp length holder
    prev_sd_len = None          # tmp previous length holder

    pattern = '[*/+-]'          # separator list

    opnd = None                 # tmp operand holder
    prev_opnd = None            # tmp previous operand holder
    reminder = exp              # tmp reminder holder
    while True:
        if reminder == '':
            break   # end if there is no more reminder

        prev_opnd = opnd
        res = re.search(pattern, reminder)
        if res:
            part = reminder[:res.start()]
            opnd = reminder[res.start():res.end()]
            reminder = reminder[res.end():]
        else:
            part = reminder
            opnd = ''
            reminder = ''

        try:
            sd_info = zPE.core.asm.parse_sd(part)
        except:
            return None
        if not sd_info[5]:
            sd_info = (sd_info[0], sd_info[1], sd_info[2],
                       0, sd_info[4], sd_info[3]
                       )
        prev_sd_len = sd_len
        (sd_val, sd_len) = zPE.core.asm.value_sd(sd_info)
        if not prev_opnd:   # first part
            exp_list.append(str(sd_val))
        elif prev_opnd in "+-":
            exp_list.extend( [ prev_opnd, str(sd_val), ] )
        else:
            sd_len = 1
            while 2 ** sd_len <= sd_val:
                sd_len += 1
            sd_val = eval(''.join( [ exp_list[-1], prev_opnd, str(sd_val), ] ))
            if prev_opnd == '*':
                prev_sd_len += sd_len - 1
            else:
                prev_sd_len -= sd_len
            exp_list[-1] = str(sd_val)
            sd_len = max(prev_sd_len, len(bin(sd_val)[2:]))

    if len(exp_list) == 1:
        sd_val = int(exp_list[0])
    else:
        sd_val = eval(''.join(exp_list))
    return "B'{0:0>{1}}'".format(bin(sd_val)[2:], sd_len)
