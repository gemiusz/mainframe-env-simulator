# modules that will be auto imported
import comp, conf

import os, sys
import pygtk
pygtk.require('2.0')
import gtk


class BaseFrame(object):
    def delete_event(self, widget, event, data = None):
        # change FALSE to TRUE and the main window will not be destroyed
        # with a "delete_event".
        return False


    def __init__(self):
        self.__key_binding_func = {
            'prog_show_config'      : lambda *arg: self.config_window.open(),
            'prog_show_error'       : lambda *arg: self.err_console.open(),
            'prog_quit'             : lambda *arg: self._sig_quit(None),
            }


        ### redirect STDOUT and STDERR to the error console
        self.err_console = comp.zErrConsole('zPE Error Console', True)
        sys.stdout = self.err_console
        sys.stderr = self.err_console

        ### retrive GUI configuration
        conf.read_rc()
        comp.zTheme.set_font(conf.Config['FONT'])
        comp.zTheme.set_color_map(conf.Config['COLOR_MAP'])

        comp.zEdit.set_style(conf.Config['MISC']['key_binding'])
        comp.zEdit.set_key_binding(conf.Config['KEY_BINDING'])

        if conf.Config['MISC']['tab_on'] == 'on':
            comp.zEdit.set_tab_on(True)
        else:
            comp.zEdit.set_tab_on(False)

        if conf.Config['MISC']['tab_mode'] == 'group':
            comp.zEdit.set_tab_grouped(True)
        else:
            comp.zEdit.set_tab_grouped(False)


        ### create config window
        self.config_window = ConfigWindow()

        ### create top-level frame
        self.root = gtk.Window(gtk.WINDOW_TOPLEVEL)

        self.root.connect("delete_event", self.delete_event)
        self.root.connect("destroy", self._sig_quit)

        self.root.set_title("zPE - Mainframe Programming Environment Simulator")
        self.root.set_icon_from_file( os.path.join(
                os.path.dirname(__file__), "image", "icon_zPE.svg"
                ) )
        self.root.set_size_request(800, 560)


        ### create layout
        w_vbox = gtk.VBox()
        self.root.add(w_vbox)


        ### create toolbar
        self.toolbar = gtk.Toolbar()
        w_vbox.pack_start(self.toolbar, False, False, 0)

        self.toolbar.set_orientation(gtk.ORIENTATION_HORIZONTAL)
        self.toolbar.set_style(gtk.TOOLBAR_ICONS)
        self.toolbar.set_tooltips(True)

        ## create toolbar buttons
        self.tool_buff_open = gtk.ToolButton(gtk.STOCK_OPEN)
        self.tool_buff_open.set_tooltip_text('Open a New Buffer')
        self.tool_buff_save = gtk.ToolButton(gtk.STOCK_SAVE)
        self.tool_buff_save.set_tooltip_text('Save Current Buffer')
        self.tool_buff_save_as = gtk.ToolButton(gtk.STOCK_SAVE_AS)
        self.tool_buff_save_as.set_tooltip_text('Save Current Buffer As ...')
        self.tool_buff_close = gtk.ToolButton(gtk.STOCK_CLOSE)
        self.tool_buff_close.set_tooltip_text('Close Current Buffer')

        self.tool_config = gtk.ToolButton(gtk.STOCK_PREFERENCES)
        self.tool_config.set_tooltip_text('Show the Config Window')
        self.tool_err_console = gtk.ToolButton(gtk.STOCK_DIALOG_WARNING)
        self.tool_err_console.set_tooltip_text('Show the Error Console')
        self.tool_quit = gtk.ToolButton(gtk.STOCK_QUIT)
        self.tool_quit.set_tooltip_text('Quit the Simulator')

        ## insert toolbar buttons
        self.toolbar.insert(self.tool_buff_open, 0)
        self.toolbar.insert(self.tool_buff_save, 1)
        self.toolbar.insert(self.tool_buff_save_as, 2)
        self.toolbar.insert(self.tool_buff_close, 3)

        self.toolbar.insert(gtk.SeparatorToolItem(), 4)

        self.toolbar.insert(self.tool_config, 5)
        self.toolbar.insert(self.tool_err_console, 6)
        self.toolbar.insert(self.tool_quit, 7)

        ## connect auto-update items
        comp.zEdit.register('buffer_focus_in', self._sig_buffer_focus_in, self)

        ## connect signals
        self.tool_buff_open.connect('clicked', self._sig_buff_manip, 'open')

        self.tool_config.connect('clicked', self.__key_binding_func['prog_show_config'])
        self.tool_err_console.connect('clicked', self.__key_binding_func['prog_show_error'])
        self.tool_quit.connect('clicked', self.__key_binding_func['prog_quit'])


        ### create main window
        self.mw = comp.zSplitScreen(comp.zEdit, [], self.frame_init, self.frame_split_dup)
        w_vbox.pack_start(self.mw, True, True, 0)


        ### create last-line
        self.lastline = comp.zLastLine('z# ')
        w_vbox.pack_end(self.lastline, False, False, 0)


        ### set accel

        ## for root window
        self.set_accel()

        ## for config window
        self.agr_conf = gtk.AccelGroup()
        self.config_window.add_accel_group(self.agr_conf)

        # ESC ==> close
        self.agr_conf.connect_group(
            gtk.keysyms.Escape,
            0,
            gtk.ACCEL_VISIBLE,
            lambda *s: self.config_window.close()
            )

        ## for error console
        self.agr_err = gtk.AccelGroup()
        self.err_console.add_accel_group(self.agr_err)

        # ESC ==> close
        self.agr_err.connect_group(
            gtk.keysyms.Escape,
            0,
            gtk.ACCEL_VISIBLE,
            lambda *s: self.err_console.close()
            )

        ### show all parts
        self.agr_err.lock()
        w_vbox.set_focus_chain((self.mw, self.lastline)) # prevent toolbar from getting focus
        self.root.show_all()

        self.err_console.setup = False # signal the end of the setup phase; no more stderr
        if self.err_console.get_text():
            self.err_console.open()


    ### signal-like auto-update function
    def _sig_buffer_focus_in(self, widget = None):
        # get current buffer
        buff = self.mw.active_frame().active_buffer
        is_file = (buff.type == 'file')
        is_dir  = (buff.type == 'dir')

        # update toolbar
        self.tool_buff_open.set_property('sensitive', not is_dir)
        self.tool_buff_save.set_property('sensitive', is_file and buff.modified)
        self.tool_buff_save_as.set_property('sensitive', is_file and buff.modified)
        self.tool_buff_close.set_property('sensitive', is_file)
    ### end of signal-like auto-update function


    ### top level signals
    def _sig_buff_manip(self, widget, task):
        # get current buffer
        frame = self.mw.active_frame()
        buff = frame.active_buffer

        if task == 'open':
            if buff.type != 'dir':
                if buff.path:
                    frame.set_buffer(buff.path[:-1], 'dir')
                else:
                    frame.set_buffer(None, 'dir')
        elif task == 'save':
            pass
        elif task == 'save-as':
            pass
        elif task == 'close':
            pass
        else:
            raise KeyError


    def _sig_quit(self, widget, data = None):
        #########################
        # check save here       #
        #########################
        gtk.main_quit()
    ### end of top level signals


    ### signals for SplitScreen
    def _sig_popup_manip(self, widget, menu, data = None):
        menu.append(gtk.SeparatorMenuItem())
        menu.append(gtk.MenuItem("test"))
        menu.show_all()
    ### end of signals for SplitScreen


    ### callback functions for SplitScreen
    def frame_init(self, frame):
        frame.connect('populate_popup', self._sig_popup_manip)

    def frame_split_dup(self, frame):
        if frame:
            new_frame = comp.zEdit(* frame.get_buffer())
        else:
            new_frame = comp.zEdit()

        return new_frame
    ### end of callback functions for SplitScreen


    ### key binding
    def set_accel(self):
        for (k, v) in conf.Config['FUNC_BINDING'].items():
            if k in self.__key_binding_func:
                comp.zEdit.register(k, self.__key_binding_func[k], self)
    ### end of key binding


    def main(self):
        gtk.main()



######## ######## ######## ########
########      Config       ########
######## ######## ######## ########

class ConfigWindow(gtk.Window):
    def __init__(self):
        super(ConfigWindow, self).__init__()

        self.set_destroy_with_parent(True)
        self.connect("delete_event", self._sig_close_console)

        self.set_title('zPE Config')


        # layout of the frame:
        # 
        #   +--+--+--+---+_
        #   +--+--+--+---+ \
        #   |            |  tab
        #   |            |
        #   |   center   |
        #   |            |
        #   |            |
        #   +------+--+--+-- separator
        #   |      |bt|bt|
        #   +------+--+--+

        layout = gtk.VBox()
        self.add(layout)

        ### create center
        self.center = gtk.Notebook()
        layout.pack_start(self.center, True, True, 0)

        ## 
        self.ct_1 = gtk.Label('page 1')
        self.center.append_page(self.ct_1, gtk.Label('tab 1'))

        # separator
        layout.pack_start(gtk.HSeparator(), False, False, 0)

        # create bottom
        self.bottom = gtk.HBox()
        layout.pack_end(self.bottom, False, False, 0)

        self.bttn_cancel = gtk.Button('Cancel', gtk.STOCK_CANCEL)
        self.bttn_save = gtk.Button('Save', gtk.STOCK_APPLY)

        self.bttn_cancel.connect('clicked', self._sig_close_console)
        self.bttn_save.connect('clicked', self._sig_save_config)

        self.bottom.pack_start(gtk.Label(), True, True, 0)
        self.bottom.pack_end(self.bttn_save, False, False, 5)
        self.bottom.pack_end(self.bttn_cancel, False, False, 5)


        layout.show_all()


    ### signal definition
    def _sig_default(self, widget):
        self.default()

    def _sig_open_console(self, *arg):
        self.open()

    def _sig_save_config(self, *arg):
        conf.write_rc()
        self.close()

    def _sig_close_console(self, *arg):
        self.close()
        return True
    ### end of signal definition


    ### overloaded function definition
    def default(self):
        pass                    # retrive info

    def open(self):
        if self.get_property('visible'):
            self.window.show()
        else:
            self.show()
        self.default()

    def close(self):
        self.hide()
    ### end of overloaded function definition


