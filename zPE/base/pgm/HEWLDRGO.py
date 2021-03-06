################################################################
# Program Name:
#     HEWLDRGO / LOADER
#
# Purpose:
#     linkage-edit the object module into a load module, execute
#     it, ant through it away
#
# Parameter:
#     not implemented yet
#
# Input:
#     SYSLIN    the object module
#     SYSLIB    load module libraries needed by the loader
#     XREAD     input for XREAD; default to instream data
#     [ ... ]   user-defined input for the module to be executed
#
# Output:
#     SYSLOUT   loader information and diagnostic message
#     XPRNT     output for XPRNT
#     XSNAPOUT  output for XDUMP and XSNAP
#     [ ... ]   user-defined output for the module to be executed
#
# Return Code:
#      0        the module ended normally
#      8        the module ended abnormally
#     12        the module is force closed by the LOADER
#     16        insufficient resources
#
# Return Value:
#     None
################################################################


from zPE.util import *
from zPE.util.conv import *
from zPE.util.excptn import *
from zPE.util.global_config import *

import zPE.util.spool as spool

import sys
from time import strftime, time
from random import randint
from binascii import b2a_hex
from threading import Timer

import zPE.base.core.cpu
import zPE.base.core.mem

# relative import resource file
from hewldrgo_config import * # read resource file for LDR config + rc


FILE_CHK = [                    # files to be checked
    'SYSLIN', 'SYSLOUT',
    ]
FILE_REQ = [                    # files that are required
    'SYSLIN', 'SYSLOUT',
    ]
FILE_GEN = {                    # files that will be generated if missing
    }


def run(step):
    '''this should prepare an tmp step and pass it to init()'''
    mark4future('user-specific pgm')


def init(step):
    # check for file requirement
    if __MISSED_FILE(step) != 0:
        return RC['CRITICAL']

    # load the user-supplied PARM and config into the default configuration
    # ldr_load_parm({
    #         })
    ldr_load_local_conf({
            'MEM_POS' : randint(512*128, 4096*128) * 8, # random from 512K to 4M
            'MEM_LEN' : region_max_sz(step.region),
                        # this is WAY to large;
                        # need a way to detect actual mem size
            'TIME'    : min(
                JCL['jobstart'] + JCL['time'] - time(), # job limit
                step.time                               # step limit
                ),
            'REGION'  : step.region,
            })

    # load OBJMOD into memory, and execute it
    rc = go(load())

    __PARSE_OUT(rc)

    ldr_init_res()              # release resources

    return rc


def load():
    '''load all OBJECT MODULEs (statically) into memory'''
    if LDR_CONFIG['MEM_LEN'] > region_max_sz(LDR_CONFIG['REGION']):
        abort(9, 'Error: ', LDR_CONFIG['REGION'],
              ': RIGEON is not big enough.\n')

    spi = spool.retrieve('SYSLIN') # input SPOOL
    mem = zPE.base.core.mem.Memory(LDR_CONFIG['MEM_POS'], LDR_CONFIG['MEM_LEN'])
    LDR_CONFIG['EXIT_PT'] = mem.h_bound

    rec_tp = { # need to be all lowercase since b2a_hex() returns all lowercase
        'ESD' : c2x('ESD').lower(),
        'TXT' : c2x('TXT').lower(),
        'RLD' : c2x('RLD').lower(),
        'END' : c2x('END').lower(),
        'SYM' : c2x('SYM').lower(),
        }
    rec_order = {
        # current type : expected type(s)
        rec_tp['ESD']  : [ rec_tp['ESD'], rec_tp['TXT'], ],
        rec_tp['TXT']  : [ rec_tp['TXT'], rec_tp['RLD'], rec_tp['END'], ],
        rec_tp['RLD']  : [ rec_tp['RLD'], rec_tp['END'], ],
        rec_tp['END']  : [ rec_tp['ESD'], None, ], # None <==> EoF
#        rec_tp['SYM']  : [  ],
        }
    expect_type = [ rec_tp['ESD'] ]     # next expected record type

    obj_id = 1            # 1st OBJECT MODULE
    mem_loc = mem.min_pos # starting memory location for each OBJMOD (RF)

    esd_id_next = 1             # next available ESD ID
    for r in spi.spool:
        rec = b2a_hex(r)
        if rec[:2] != '02':     # control statement
            field = resplit_sq(r'\s+', rec, 3)
            if len(field) < 3  or  field[0] != '':
                abort(13, "Error: ", rec,
                      ":\n invalid OBJECT MODULE control statement.\n")

            if field[1] == 'ENTRY':
                LDR_CONFIG['ENTRY_PT'] = '{0:<8}'.format(field[2])

            elif field[1] == 'INCLUDE':
                mark4future('OM INCLUDE statement')

            elif field[1] == 'NAME':
                pass            # only the linkage-editor need this

            else:
                abort(13, "Error: ", rec,
                      ":\n invalid OBJECT MODULE control statement.\n")
            continue

        # check record type
        if rec[2:8] not in expect_type:
            sys.stderr.write(
                'Error: Loader: Invalid OBJECT MODULE record encountered.\n'
                )
            return RC['ERROR']  # OBJECT module format error
        else:
            expect_type = rec_order[rec[2:8]]

        # parse ESD record
        if rec[2:8] == rec_tp['ESD']: # byte 2-4
            byte_cnt = int(rec[20:24], 16) # byte 11-12: byte count
            esd_id = rec[28:32]            # byte 15-16: ESD ID / blank
            if esd_id == c2x('  '):        # 2 spaces
                # blank => 'LD'
                esd_id = None   # no advancing in ESD ID
            else:
                # non-blank, parse it to int
                esd_id = int(esd_id, 16)
                esd_id_next = esd_id + 1
            for i in [ 32 + j * 32                   # vf indx -> start pos
                       for j in range(byte_cnt / 16) # number of vf
                       ]:
                vf = rec[i : i+32] # each vf is 16 bytes long
                addr = int(vf[18:24], 16) # vf byte 10-12: address
                length = vf[26:32]        # vf byte 14-16: length / blank
                if length == c2x('   '):  # 3 spaces
                    length = None
                else:
                    length = int(length, 16)
                esd = ExternalSymbol(
                    None, esd_id, addr, length,
                    None, LDR_PARM['AMODE'], LDR_PARM['RMODE'], None
                    )
                esd.load_type(vf[16:18])  # vf byte 9: ESD type code
                esd_name = x2c(vf[0:16])  # vf byte 1-8: ESD Name
                if esd.type in [ 'SD', 'PC', ]:
                    CSECT[obj_id, esd.id] = ( mem_loc, esd, esd_name )
                    SCOPE[mem_loc, esd.addr, esd.length] = ( obj_id, esd.id )

                    if esd_name == LDR_CONFIG['ENTRY_PT']:
                        LDR_CONFIG['ENTRY_PT'] = mem_loc

                elif esd.type == 'ER':
                    EXREF[obj_id, esd.id] = ( 0,       esd, esd_name)
                else:
                    pass        # ignore the rest
                # advance ESD ID by 1
                esd_id = esd_id_next
                esd_id_next = esd_id + 1

        # parse TXT record
        elif rec[2:8] == rec_tp['TXT']: # byte 2-4
            addr = int(rec[10:16], 16)     # byte 6-8: starting address
            byte_cnt = int(rec[20:24], 16) # byte 11-12: byte count
            scope = int(rec[28:32], 16)    # byte 15-16: scope id

            if ( obj_id, scope ) not in CSECT:
                abort(13, 'Error: ', str(scope),
                      ': Invalid ESD ID in TXT record(s).\n')

            # calculate the actual location
            loc = ( CSECT[obj_id, scope][0] +      # start of OBJMOD
                    addr                           # addr into OBJMOD
                    )
            mem[loc] = rec[32 : 32 + byte_cnt * 2]

        # parse RLD record
        elif rec[2:8] == rec_tp['RLD']: # byte 2-4
            byte_cnt = int(rec[20:24], 16) # byte 11-12: byte count
            remainder = rec[32 : 32 + byte_cnt * 2]
            df_same = False     # not the same ESDID
            while remainder:
                if not df_same: # update ESDID if needed
                    rel_id = int(remainder[  : 4], 16)
                    pos_id = int(remainder[4 : 8], 16)
                    remainder = remainder[8:]
                # parsing flags
                df_vcon = (remainder[0] == '1') # 1st hex-digit: v-con flag
                df_flag = int(remainder[1], 16) # 2nd hex-digit: flags
                df_len  = (df_flag >> 2) + 1    # 2.1 - 2.2: length - 1
                df_neg  = bool(df_flag & 0b10)  # 2.3: negative flag
                df_same = bool(df_flag & 0b01)  # 2.4: same ESDID flag

                # retrieving address
                df_addr = int(remainder[2:8], 16)
                remainder = remainder[8:]

                df_addr += mem_loc # re-mapping the memory address
                if df_neg:
                    reloc_offset = - mem_loc
                else:
                    reloc_offset = mem_loc

                # get the original value of the address constant
                if df_vcon:
                    found = False
                    for val in CSECT.itervalues():
                        if ( val[2] == EXREF[obj_id, rel_id][2] and
                             val[1].type == 'SD'
                             ):
                            reloc_value = val[1].addr
                            found = True
                            break
                    if not found:
                        abort(13, 'Error: ', EXREF[obj_id, rel_id][2],
                              ': Storage Definition not found.\n')
                else:
                    reloc_value = int(mem[df_addr : df_addr + df_len], 16)

                # relocate the address constant
                reloc_value += reloc_offset
                mem[df_addr] = '{0:0>{1}}'.format(
                    i2h(reloc_value)[- df_len * 2 : ], # max len
                    df_len * 2                         # min len
                    )

        # parse END record
        elif rec[2:8] == rec_tp['END']: # byte 2-4
            # setup ENTRY POINT, if not offered by the user
            if LDR_CONFIG['ENTRY_PT'] == None:
                # no ENTRY POINT offered, nor setup by a previous OBJMOD
                entry = rec[10:16] # byte 6-8: entry point
                if entry == c2x('   '): # 3 spaces
                    scope = 1   # no ENTRY POINT in END, use 1st CSECT
                    loc = CSECT[obj_id, scope][1].addr
                else:
                    scope = int(rec[28:32], 16) # byte 15-16: ESD ID for EP
                    loc = int(entry, 16)
                loc += CSECT[obj_id, scope][0] # add the offset of the OBJMOD
                LDR_CONFIG['ENTRY_PT'] = loc
            elif isinstance(LDR_CONFIG['ENTRY_PT'], str):
                # CSECT name not found
                sys.stderr.write(
                    'Error: {0}: Invalid Entry Point specified.\n'.format(
                        LDR_CONFIG['ENTRY_PT']
                        )
                    )
                return RC['ERROR'] # OBJECT module format error

            # prepare for next OBJECT MODULE, if any
            max_offset = 0
            for key in CSECT:
                if key[0] == obj_id:
                    offset = CSECT[key][1].addr + CSECT[key][1].length
                    if max_offset < offset:
                        max_offset = offset
            # advance to next available loc, align to double-word boundary
            mem_loc = (mem_loc + max_offset + 7) / 8 * 8
            obj_id += 1     # advance OBJECT MODULE counter

            esd_id_next = 1 # reset next available ESD ID

        # parse SYM record
        elif rec[2:8] == rec_tp['SYM']: # byte 2-4
            pass                # currently not supported


    # check end state
    if None not in expect_type:
        sys.stderr.write(
            'Error: Loader: OBJECT MODULE not end with END card.\n'
            )
        return RC['ERROR']      # OBJECT module format error

    if debug_mode():
        print 'Memory after loading Object Deck:'
        for line in mem.dump_all():
            print line[:-1]
        print

    return mem
# end of load()

def go(mem):
    if mem.__class__ is not zPE.base.core.mem.Memory:
        return mem # not a Memory instance, error occured during loading

    psw = SPR['PSW']
    ldr_mem = zPE.base.core.mem.Memory(
        (mem.max_pos + 7) / 8 * 8, # align on next doubleword boundary
        18 * 4                     # 18F RSV
        )
    ldr_mem[ldr_mem.min_pos] = c2x('RSV ') * 18

    prsv = GPR[13] # register 13: parent register saving area
    rtrn = GPR[14] # register 14: return address
    enty = GPR[15] # register 15: entry address

    # initial program load
    prsv[0] = ldr_mem.min_pos        # load LOADER's RSV into register 13
    rtrn[0] = LDR_CONFIG['EXIT_PT']  # load exit point into register 14
    enty[0] = LDR_CONFIG['ENTRY_PT'] # load entry point into register 15
    psw.Instruct_addr = LDR_CONFIG['ENTRY_PT'] # set PSW accordingly

    old_key = psw.PSW_key       # backup previous PSW key
    psw.PSW_key = LDR_PARM['PSWKEY']
    psw.M = 1                   # turn on "Machine check"
    psw.W = 0                   # content switch to the program

    # main execution loop
    timeouted = [ ]
    def timeout():
        timeouted.append(True)
    t = Timer(LDR_CONFIG['TIME'], timeout)
    try:
        t.start()               # start the timer
        RECORD_BR(psw.snapshot(), ['00', '00']) # branch into the module
        while not timeouted  and  psw.Instruct_addr != LDR_CONFIG['EXIT_PT']:
            zPE.base.core.cpu.execute(
                RECORD_INS(psw.snapshot(), zPE.base.core.cpu.fetch())
                )
        t.cancel()              # stop the timer
        rc = RC['NORMAL']
    except Exception as e:
        # ABEND CODE; need info
        t.cancel()              # stop the timer
        if isinstance(e, zPException):
            e_push(e)
        else:
            if debug_mode():
                raise
            else:
                sys.stderr.write( # print out the actual error
                    'Exception: {0}\n'.format(
                        ', '.join([ str(arg) for arg in e.args ])
                        )
                    )
            e_push( newSystemException('0C0', 'UNKNOWN EXCEPTION') )
        MEM_DUMP.extend(mem.dump_all())
        rc = RC['ERROR']        # OBJECT module abnormally ended
    if timeouted:
        e_push( newSystemException(
                '322', 'TIME EXCEEDED THE SPECIFIED LIMIT'
                ) )
        MEM_DUMP.extend(mem.dump_all())
        rc = RC['SEVERE']       # OBJECT module force closed

    psw.W = 1                   # content switch back to the loader
    psw.PSW_key = old_key       # restore PSW key

    mem.release()
    ldr_mem.release()

    if debug_mode():
        sys.stderr.write(e_dump())
    return rc
# end of go()


### Supporting Functions
def __MISSED_FILE(step):
    sp1 = spool.retrieve('JESMSGLG') # SPOOL No. 01
    sp3 = spool.retrieve('JESYSMSG') # SPOOL No. 03
    ctrl = ' '

    cnt = 0
    for fn in FILE_CHK:
        if fn not in spool.list():
            sp1.append(ctrl, strftime('%H.%M.%S '), JCL['jobid'],
                       '  IEC130I {0:<8}'.format(fn),
                       ' DD STATEMENT MISSING\n')
            sp3.append(ctrl, 'IEC130I {0:<8}'.format(fn),
                       ' DD STATEMENT MISSING\n')

            if fn in FILE_REQ:
                cnt += 1
            else:
                FILE_GEN[fn]()

    return cnt


def __PARSE_OUT(rc):
    spo = spool.retrieve('SYSLOUT') # output SPOOL

