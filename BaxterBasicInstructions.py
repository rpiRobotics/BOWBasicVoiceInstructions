#!/usr/bin/python

import RobotRaconteur as RR
import sys, argparse, select
import copy
import threading

from gi import pygtkcompat
import gi

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst
GObject.threads_init()
Gst.init(None)

gst = Gst

print("Using pygtkcompat and Gst from gi")

pygtkcompat.enable()
pygtkcompat.enable_gtk(version='3.0')

import gtk


voice_cmd_servicedef="""
# Service to provide xbox controller like interface to voice commands
service VoiceCmd_Interface

option version 0.5

struct XboxControllerInput
    field int32 A
    field int32 B
    field int32 X
    field int32 Y
    field int32 left_thumbstick_X
    field int32 left_thumbstick_Y
    field int32 right_thumbstick_X
    field int32 right_thumbstick_Y
end struct

object VoiceCmd
    property XboxControllerInput controller_input
end object

"""

class voice_cmd(object):
    """GStreamer/PocketSphinx Baxter Voice Command Application"""

    def __init__(self):
        """Initialize a voice_cmd object"""
        self.init_gui()
        self.init_gst()
        self._controller_input = None
        self._paused = 0
        self._vel_change = 0
        self._prev_motion_hyp = ''
        self._text_cmd = '\0'

        # start background threads
        self._running = True
        self._t_worker = threading.Thread(target=self.text_worker)
        self._t_worker.daemon = True
        self._t_worker.start()

    def close(self):
        print "Closing Node"
        self._running = False
        self._t_worker.join()

    # worker function to get text inputs
    def text_worker(self):
        while self._running:
            while sys.stdin in select.select([sys.stdin], [], [], 0)[0]:
                self._text_cmd = sys.stdin.readline().strip()

                if self.pipeline.get_state(0)[0] == gst.State.PAUSED:
                    self.xbox_cmd(self._text_cmd)

    def init_gui(self):
        """Initialize the GUI components"""
        self.window = gtk.Window()
        self.window.connect("delete-event", gtk.main_quit)
        self.window.set_default_size(400,200)
        self.window.set_border_width(10)
        vbox = gtk.VBox()
        self.textbuf = gtk.TextBuffer()
        self.text = gtk.TextView(buffer=self.textbuf)
        self.text.set_wrap_mode(gtk.WRAP_WORD)
        vbox.pack_start(self.text)
        self.button = gtk.ToggleButton("Type")
        self.button.connect('clicked', self.button_clicked)
        vbox.pack_start(self.button, False, False, 5)
        self.window.add(vbox)
        self.window.show_all()

    def init_gst(self):
        """Initialize the speech components"""
        self.pipeline = gst.parse_launch('autoaudiosrc ! audioconvert ! audioresample '
                                         + '! pocketsphinx name=asr ! fakesink')
        asr = self.pipeline.get_by_name('asr')
        asr.set_property('lm', 'baxter_cmd.lm')
        asr.set_property('dict', 'baxter_cmd.dic')
        asr.set_property('configured', True)
        bus = self.pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect('message::element', self.element_message)

        self.pipeline.set_state(gst.State.PAUSED)

    def element_message(self, bus, msg):
        """Receive element messages from the bus."""
        msgtype = msg.get_structure().get_name()
        if msgtype != 'pocketsphinx':
            return

        if msg.get_structure()['final']:
            self.final_result(msg.get_structure()['hypothesis'], msg.get_structure()['confidence'])

    def final_result(self, hyp, confidence):
        """Insert the final result."""

        if (hyp=='RESUME'):
            self.button.set_label("Speak")
            self._paused = 0
        if (hyp=='PAUSE'):
            self.button.set_label("Pause")
            self._paused = 1

        if (self._paused != 1):
            self.xbox_cmd(hyp)

            # All this stuff appears as one single action
            self.textbuf.begin_user_action()
            self.textbuf.delete_selection(True, self.text.get_editable())
            self.textbuf.insert_at_cursor(hyp+'     ')
            self.textbuf.end_user_action()

    def button_clicked(self, button):
        """Handle button presses."""
        if button.get_active():
            button.set_label("Speak")
            self.pipeline.set_state(gst.State.PLAYING)
        else:
            button.set_label("Type")
            self.pipeline.set_state(gst.State.PAUSED)

    def init_xbox_cmd(self):
        if (self._controller_input is None):
            self._controller_input = RR.RobotRaconteurNode.s.NewStructure("VoiceCmd_Interface.XboxControllerInput")

            # initialize structure to zero values
            self._controller_input.A = 0
            self._controller_input.B = 0
            self._controller_input.X = 0
            self._controller_input.Y = 0
            self._controller_input.left_thumbstick_X = 0
            self._controller_input.left_thumbstick_Y = 0
            self._controller_input.right_thumbstick_X = 0
            self._controller_input.right_thumbstick_Y = 0

    def xbox_cmd(self, hyp):
        """Convert voice commands to their xbox equivalent."""
        self._controller_input.A = 1 if (hyp=='SWITCH') else 0
        self._controller_input.B = 1 if (hyp=='SHUTDOWN') else 0
        self._controller_input.X = 0
        self._controller_input.Y = 1 if (hyp=='GRIPPER') else 0

        if (hyp=='FAST'):
            self._vel_change = 1000
        if (hyp=='FASTER'):
            self._vel_change = 2500
        if (hyp=='SLOW'):
            self._vel_change = -1000
        if (hyp=='SLOWER'):
            self._vel_change = -2500
        if (hyp=='SPEED UP'):
            self._vel_change = 250
        if (hyp=='SLOW DOWN'):
            self._vel_change = -250

        if (hyp=='STOP'):
            self._vel_change = 0
            self._controller_input.left_thumbstick_X = 0
            self._controller_input.left_thumbstick_Y = 0
            self._controller_input.right_thumbstick_X = 0
            self._controller_input.right_thumbstick_Y = 0

        if (hyp=='RIGHT' or hyp=='LEFT' or hyp=='FORWARD' or hyp=='BACKWARD' or hyp=='UP' or hyp=='DOWN'):
            self._prev_motion_hyp = hyp

        if (hyp=='FAST' or hyp=='FASTER' or hyp=='SLOW' or hyp=='SLOWER' or hyp=='SPEED UP' or hyp=='SLOW DOWN'):
            if (self._prev_motion_hyp=='RIGHT'):
                self._controller_input.left_thumbstick_X += self._vel_change
                if (self._controller_input.left_thumbstick_X > 10000):
                    self._controller_input.left_thumbstick_X = 10000
                if (self._controller_input.left_thumbstick_X < 0):
                    self._controller_input.left_thumbstick_X = 0
            if (self._prev_motion_hyp=='LEFT'):
                self._controller_input.left_thumbstick_X -= self._vel_change
                if (self._controller_input.left_thumbstick_X < -10000):
                    self._controller_input.left_thumbstick_X = -10000
                if (self._controller_input.left_thumbstick_X > 0):
                    self._controller_input.left_thumbstick_X = 0
            if (self._prev_motion_hyp=='FORWARD'):
                self._controller_input.left_thumbstick_Y += self._vel_change
                if (self._controller_input.left_thumbstick_Y > 10000):
                    self._controller_input.left_thumbstick_Y = 10000
                if (self._controller_input.left_thumbstick_Y < 0):
                    self._controller_input.left_thumbstick_Y = 0
            if (self._prev_motion_hyp=='BACKWARD'):
                self._controller_input.left_thumbstick_Y -= self._vel_change
                if (self._controller_input.left_thumbstick_Y < -10000):
                    self._controller_input.left_thumbstick_Y = -10000
                if (self._controller_input.left_thumbstick_Y > 0):
                    self._controller_input.left_thumbstick_Y = 0
            if (self._prev_motion_hyp=='UP'):
                self._controller_input.right_thumbstick_Y += self._vel_change
                if (self._controller_input.right_thumbstick_Y > 10000):
                    self._controller_input.right_thumbstick_Y = 10000
                if (self._controller_input.right_thumbstick_Y < 0):
                    self._controller_input.right_thumbstick_Y = 0
            if (self._prev_motion_hyp=='DOWN'):
                self._controller_input.right_thumbstick_Y -= self._vel_change
                if (self._controller_input.right_thumbstick_Y < -10000):
                    self._controller_input.right_thumbstick_Y = -10000
                if (self._controller_input.right_thumbstick_Y > 0):
                    self._controller_input.right_thumbstick_Y = 0

    @property
    def controller_input(self):
        controller_input = copy.copy(self._controller_input)
        self._controller_input.A = 0
        self._controller_input.B = 0
        self._controller_input.X = 0
        self._controller_input.Y = 0
        return controller_input

def main(argv):
    # parse command line arguments
    parser = argparse.ArgumentParser(description='Initialize.')
    parser.add_argument('--port', type=int, default = 0,
                        help='TCP port to host service on' + \
                        '(will auto-generate if not specified)')
    args = parser.parse_args(argv)

    # Enable numpy
    RR.RobotRaconteurNode.s.UseNumPy=True

    # Set the Node name
    RR.RobotRaconteurNode.s.NodeName="VoiceCmdServer"

    # Initialize object
    voice_cmd_obj = voice_cmd()

    # Create transport, register it, and start the server
    print "Registering Transport"
    t = RR.TcpTransport()
    t.EnableNodeAnnounce(RR.IPNodeDiscoveryFlags_NODE_LOCAL |
                         RR.IPNodeDiscoveryFlags_LINK_LOCAL |
                         RR.IPNodeDiscoveryFlags_SITE_LOCAL)

    RR.RobotRaconteurNode.s.RegisterTransport(t)
    t.StartServer(args.port)
    port = args.port
    if (port == 0):
        port = t.GetListenPort()

    # Register the service type and the service
    print "Starting Service"
    RR.RobotRaconteurNode.s.RegisterServiceType(voice_cmd_servicedef)
    RR.RobotRaconteurNode.s.RegisterService("VoiceCmd", "VoiceCmd_Interface.VoiceCmd", voice_cmd_obj)

    print "Service started, connect via"
    print "tcp://localhost:" + str(port) + "/VoiceCmdServer/VoiceCmd"
    voice_cmd_obj.init_xbox_cmd()
    gtk.main()

    # Safely close
    voice_cmd_obj.close()

    # This must be here to prevent segfault
    RR.RobotRaconteurNode.s.Shutdown()

if __name__ == '__main__':
    main(sys.argv[1:])
