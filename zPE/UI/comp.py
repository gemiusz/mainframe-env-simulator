# this is the UI components file

import zPE

import os, sys
import pygtk
pygtk.require('2.0')
import gtk
import gobject


class MainWindow(gtk.Frame):
    def __init__(self):
        super(MainWindow, self).__init__()

        # layout of the frame:
        # 
        #   0 1          2 3
        # 0 +-+----------+-+ 0
        #   | |    tp    | |
        # 1 +-+----------+-+ 1
        #   | |          | |
        #   | |          | |
        #   |l|    mw    |r|
        #   |t|          |t|
        #   | |          | |
        #   | |----------| |
        # 2 +-+----------+-+ 2
        #   | |    bm    | |
        # 3 +-+----------+-+ 3
        #   0 1          2 3

        root_frame = gtk.Table(3, 3, False)
        self.add(root_frame)

        self.sd_layer = None    # init shading-layer to None

        self.__mw_frame_sz = (40, 40) # the minimum size required for each MainWindowFrame
        self.__ctrl_pos = {
            'a' : ( 'lt', 'rt', 'tp', 'bm', ), # all
            'b' : ( 'lt',       'tp',       ), # begin
            'e' : (       'rt',       'bm', ), # end
            'h' : ( 'lt', 'rt',             ), # horizontal
            'v' : (             'tp', 'bm', ), # vertical
            }
        self.ctrl_bar = {}
        self.ctrl_bar['lt'] = gtk.Button()
        self.ctrl_bar['rt'] = gtk.Button()
        self.ctrl_bar['tp'] = gtk.Button()
        self.ctrl_bar['bm'] = gtk.Button()
        self.mw_center = gtk.Frame()
        self.mw_center.add(self.new_frame())

        root_frame.attach(self.ctrl_bar['lt'], 0, 1, 1, 2, xoptions=gtk.SHRINK)
        root_frame.attach(self.ctrl_bar['rt'], 2, 3, 1, 2, xoptions=gtk.SHRINK)
        root_frame.attach(self.ctrl_bar['tp'], 1, 2, 0, 1, yoptions=gtk.SHRINK)
        root_frame.attach(self.ctrl_bar['bm'], 1, 2, 2, 3, yoptions=gtk.SHRINK)
        root_frame.attach(self.mw_center,      1, 2, 1, 2)

        # connect signals for control-bars
        drag_icon = gtk.gdk.pixbuf_new_from_file(
            os.path.join(os.path.dirname(__file__), "image", "min_empty.gif")
            )
        for pos in self.__ctrl_pos['a']:
            self.ctrl_bar[pos].set_property('can_focus', False)
            self.ctrl_bar[pos].connect_object('clicked', self.add_paned, self.mw_center, pos)
            self.ctrl_bar[pos].drag_source_set(gtk.gdk.BUTTON1_MASK, [], 0)
            self.ctrl_bar[pos].connect('drag_begin', self._sig_ctrl_drag, drag_icon, pos)
            self.ctrl_bar[pos].connect('button-release-event', self._sig_ctrl_drop, pos)


    ### signal for DnD
    def _sig_ctrl_drag(self, widget, context, icon, pos):
        context.set_icon_pixbuf(icon, 0, 0)

        # create the shading-layer
        root = widget.get_root_window()
        (root_w, root_h) = root.get_size()
        screen = widget.get_toplevel().get_screen()
        self.sd_layer = gtk.gdk.Window(
            root, root_w, root_h,
            gtk.gdk.WINDOW_TEMP,
            gtk.gdk.ALL_EVENTS_MASK,
            gtk.gdk.INPUT_OUTPUT,
            '', 0, 0,
            screen.get_rgba_visual(), screen.get_rgba_colormap(), gtk.gdk.Cursor(gtk.gdk.PLUS),
            '', '', True
            )
        self.sd_layer.show()

        # create the cairo context
        self.sd_layer_cr = self.sd_layer.cairo_create()

        self.sd_layer_cr.set_line_width(1)
        self.sd_layer_cr.set_source_rgba(0, 0, 0, 0.3)

        # start the timer
        self.mw_center.timer = True
        gobject.timeout_add(20, self.update_mw, pos)

    def _sig_ctrl_drop(self, widget, event, pos):
        # remove the shading-layer
        if self.sd_layer:
            self.sd_layer.destroy()
            self.sd_layer = None

        # stop the timer
        self.mw_center.timer = False

        # calculate position
        alloc = self.mw_center.get_allocation()
        ptr_pos = self.mw_center.get_pointer()

        correct_pos = self._correct_pos(
            ptr_pos,                               # the current ptr pos
            (0, 0),                                # the frame size - low bound
            (alloc.width, alloc.height),           # the frame size - high bound
            [sp + 10 for sp in self.__mw_frame_sz] # the min spacing + 10
            )

        # add paned if in center
        if correct_pos:
            paned = self.add_paned(self.mw_center, pos)

            # re-position the newly added frame
            if pos in self.__ctrl_pos['h']:
                # -6 to cancel the width of the divider
                paned.set_position(correct_pos[0] - 6)
            else:
                paned.set_position(correct_pos[1] - 6)
    ### end of signal for DnD

    ### signal for MWF
    def _sig_div_drop(self, widget, event):
        for child in widget.get_children():
            alloc = child.get_allocation()
            if ( alloc.width < self.__mw_frame_sz[0] or
                 alloc.height < self.__mw_frame_sz[1]
                 ):
                self.rm_frame(widget, child)
                break

    def _sig_popup_manip(self, widget, menu):
        menu.remove(menu.get_children()[-1])
        menu.append(gtk.MenuItem("test"))
        menu.show_all()
    ### end of signal for MWF


    def new_frame(self, f_type = None, f_data = None):
        # prepare frame info
        if f_type in (None, 'textview'):
            widget = gtk.TextView()
        else:
            widget = gtk.Lable("Error: MainWindow.new_frame():\n" +
                               "       f_type not supported.\n")

        frame = MainWindowFrame(widget, f_data)
        frame.ct_pop_id = frame.connect_center('populate-popup', self._sig_popup_manip)

        return frame

    def add_paned(self, parent, pos):
        child = parent.child

        # create new paned
        if pos in self.__ctrl_pos['h']:
            paned = gtk.HPaned()
        else:
            paned = gtk.VPaned()

        # re-parent the widgets
        parent.remove(child)
        if pos in self.__ctrl_pos['b']:
            paned.pack1(self.new_frame(), True, True)
            paned.pack2(child, True, True)
        else:
            paned.pack1(child, True, True)
            paned.pack2(self.new_frame(), True, True)
        parent.add(paned)

        # connect signals
        paned.connect('button-release-event', self._sig_div_drop)

        parent.show_all()
        return paned

    def rm_frame(self, widget, child_rm):
        if widget == self.mw_center:    # the only frame
            widget.remove(child_rm)
            widget.add(self.new_frame())
            return              # early return

        # not the only frame, get parent and child info
        parent = widget.get_parent()
        if child_rm == widget.get_child1():
            child_kp = widget.get_child2() 
        else:
            child_kp = widget.get_child1() 

        # remove both child
        widget.remove(child_rm)
        widget.remove(child_kp)

        if parent == self.mw_center:    # parent is mw_center
            parent.remove(widget)
            parent.add(child_kp)
        else:                           # parent is paned
            if widget == parent.get_child1():
                add_cmd = 'parent.pack1(child_kp, True, True)'
            else:
                add_cmd = 'parent.pack2(child_kp, True, True)'
            parent.remove(widget)
            eval(add_cmd)

    def update_mw(self, pos):
        if not self.mw_center.timer:
            return False

        # calculate position
        alloc = self.mw_center.get_allocation()
        ( ptr_x,     ptr_y     ) = self.mw_center.get_pointer()
        ( ptr_abs_x, ptr_abs_y ) = self.sd_layer.get_pointer()[:2]
        ( base_x,    base_y    ) = ( ptr_abs_x - ptr_x, ptr_abs_y - ptr_y )

        self.sd_layer.clear()

        # validate position
        correct_pos = self._correct_pos(
            (ptr_x, ptr_y),                        # the current ptr pos
            (0, 0),                                # the frame size - low bound
            (alloc.width, alloc.height),           # the frame size - high bound
            [sp + 10 for sp in self.__mw_frame_sz] # the min spacing + 10
            )
        if not correct_pos:
            return True

        # draw on shading-layer
        if pos == 'lt':
            self.sd_layer_cr.rectangle(base_x,    base_y,    ptr_x,               alloc.height        )
        elif pos == 'tp':
            self.sd_layer_cr.rectangle(base_x,    base_y,    alloc.width,         ptr_y               )
        elif pos == 'rt':
            self.sd_layer_cr.rectangle(ptr_abs_x, base_y,    alloc.width - ptr_x, alloc.height        )
        else:
            self.sd_layer_cr.rectangle(base_x,    ptr_abs_y, alloc.width,         alloc.height - ptr_y)

        self.sd_layer_cr.fill()

        return True

    # all three args should all be tuples/lists with the same length
    def _correct_pos(self, pos, limit_low, limit_high, spacing):
        ct_pos = [None] * len(pos)
        for i in range(len(pos)):
            if pos[i] < limit_low[i] or pos[i] > limit_high[i]:
                return None

            if pos[i] < limit_low[i] + spacing[i]:
                ct_pos[i] = limit_low[i] + spacing[i]
            elif pos[i] > limit_high[i] - spacing[i]:
                ct_pos[i] = limit_high[i] - spacing[i]
            else:
                ct_pos[i] = pos[i]
        return ct_pos


class MainWindowFrame(gtk.VBox):
    def __init__(self, widget, buffer_name):
        super(MainWindowFrame, self).__init__()
        self.active_buff = ''

        # create the main window frame
        self.center = None
        self.switch(widget, buffer_name)

        # create the status bar
        self.bottom = gtk.Button('test')
        self.pack_end(self.bottom, False, False, 0)

    def connect_center(self, sig, cb):
        if sig in [ 'populate-popup' ]:
            if isinstance(self.center, gtk.TextView):
                return self.center.connect('populate-popup', cb)

    def switch(self, widget, buffer_name):
        # switch widget
        if self.center:
            self.remove(self.center)
        self.center = widget
        self.pack_start(self.center, True, True, 0)

        if buffer_name != self.active_buff:
            # switch buffer
            self.active_buff = buffer_name
