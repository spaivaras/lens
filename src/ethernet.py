# For Linux

ETH_P_ALL = 3 

import dpkt
import driver
import errno
import functools
import select
import socket
import subprocess
import sys

import tornado.ioloop
import tornado.iostream
import tornado.gen as gen

from base import NetLayer

class LinkLayer(NetLayer):
    SNAPLEN=1550

    ALICE = 0
    BOB = 1

    def __init__(self, alice_nic = "tapa", bob_nic = "tapb", *args, **kwargs):
        super(LinkLayer, self).__init__(*args, **kwargs)
        alice_sock = self.attach(alice_nic)
        bob_sock = self.attach(bob_nic)

        io_loop = tornado.ioloop.IOLoop.instance()

        self.alice_stream = tornado.iostream.IOStream(alice_sock)
        self.bob_stream = tornado.iostream.IOStream(bob_sock)

        io_loop.add_handler(alice_sock.fileno(), self.alice_read, io_loop.READ)
        io_loop.add_handler(bob_sock.fileno(), self.bob_read, io_loop.READ)

    @staticmethod
    def attach(nic):
        result = subprocess.call(["ip","link","set","up","promisc","on","dev",nic])
        if result:
            raise Exception("ip link dev {0} returned exit code {1}".format(nic,result))
        sock = socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(ETH_P_ALL))
        sock.bind((nic,0))
        sock.setblocking(0)
        return sock

    # coroutine
    def alice_read(self, fd, event):
        data = self.alice_stream.socket.recv(self.SNAPLEN)
        return self.on_read(self.ALICE, {}, data[:-2])

    # coroutine
    def bob_read(self, fd, event):
        data = self.bob_stream.socket.recv(self.SNAPLEN)
        return self.on_read(self.BOB, {}, data[:-2])

    # coroutine
    def write(self, dst, header, data):
        if dst == self.ALICE:
            return self.alice_stream.write(data)
        elif dst == self.BOB:
            return self.bob_stream.write(data)
        else:
            raise Exception("Bad destination")

class EthernetLayer(NetLayer):
    NAME = "eth"

    def __init__(self, *args, **kwargs):
        super(EthernetLayer, self).__init__(*args, **kwargs)
        self.seen_macs = {k: set() for k in self.routing.keys()}

    @staticmethod
    def pretty_mac(mac):
        return ":".join(["{:02x}".format(ord(x)) for x in mac])
    @staticmethod
    def wire_mac(mac):
        return "".join([chr(int(x, 16)) for x in mac.split(":")])

    @gen.coroutine
    def on_read(self, src, header, data):
        try:
            pkt = dpkt.ethernet.Ethernet(data)
        except dpkt.NeedData:
            yield self.passthru(src, header, data)
            return
        header = {
            "eth_dst": self.pretty_mac(pkt.dst),
            "eth_src": self.pretty_mac(pkt.src),
            "eth_type": pkt.type,
        }
        self.seen_macs[src].add(header["eth_src"])
        yield self.bubble(src, header, pkt.data)

    @gen.coroutine
    def write(self, dst, header, payload):
        pkt = dpkt.ethernet.Ethernet(
                dst=self.wire_mac(header["eth_dst"]),
                src=self.wire_mac(header["eth_src"]),
                type=header["eth_type"],
                data=payload)
        yield self.write_back(dst, header, str(pkt))

    def do_list(self):
        """List MAC addresses that have sent data to attached NICs."""
        output = ""
        for src, macs in self.seen_macs.items():
            output += "Source %d:\n" % src
            for mac in macs:
                output += " - %s\n" % mac
        return output


#def eth_callback(layer, src, fd, events):
#    #while True:
#    for i in range(events):
#        try:
#            layer.on_read(src)
#        except socket.error as e:
#            if e.args[0] not in (errno.EWOULDBLOCK, errno.EAGAIN):
#                raise
#            return
#
#def build_dummy_loop(*args, **kwargs):
#    io_loop = tornado.ioloop.IOLoop.instance()
#    link_layer = LinkLayer([])
#    return io_loop, link_layer
#
#def build_ethernet_loop(alice_nic="tapa", bob_nic="tapb"):
#    alice_sock = attach(alice_nic)
#    bob_sock = attach(bob_nic)
#
#    def write_fn(sock):
#        def _fn(data):
#            return sock.send(data)
#        return _fn
#
#    io_loop = tornado.ioloop.IOLoop.instance()
#
#    alice_stream = tornado.iostream.IOStream(alice_sock)
#    bob_stream = tornado.iostream.IOStream(bob_sock)
#
#    link_layer = LinkLayer([alice_stream, bob_stream])
#
#    alice_cb = functools.partial(eth_callback, link_layer, 0)
#    bob_cb = functools.partial(eth_callback, link_layer, 1)
#
#    io_loop.add_handler(alice_sock.fileno(), alice_cb, io_loop.READ)
#    io_loop.add_handler(bob_sock.fileno(), bob_cb, io_loop.READ)
#
#    return io_loop, link_layer
#
