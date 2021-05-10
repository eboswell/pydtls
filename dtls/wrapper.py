# -*- coding: utf-8 -*-

# DTLS Socket: A wrapper for a server and client using a DTLS connection.

# Copyright 2017 Björn Freise
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# The License is also distributed with this work in the file named "LICENSE."
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""DTLS Socket

This wrapper encapsulates the state and behavior associated with the connection
between the OpenSSL library and an individual peer when using the DTLS
protocol.

Classes:

  DtlsSocket -- DTLS Socket wrapper for use as a client or server
"""

import select
import time
import collections
from logging import getLogger

import ssl
import socket
from .patch import do_patch
do_patch()
from .sslconnection import SSLContext, SSL
from .err import *

_logger = getLogger(__name__)


def wrap_client(sock, keyfile=None, certfile=None,
                cert_reqs=ssl.CERT_NONE, ssl_version=ssl.PROTOCOL_DTLSv1_2, ca_certs=None,
                do_handshake_on_connect=True, suppress_ragged_eofs=True,
                ciphers=None, curves=None, sigalgs=None, user_mtu=None,
                client_cert_options=ssl.SSL_BUILD_CHAIN_FLAG_NONE,
                ssl_logging=False, handshake_timeout=None):

    return DtlsSocket(sock=sock, keyfile=keyfile, certfile=certfile, server_side=False,
                      cert_reqs=cert_reqs, ssl_version=ssl_version, ca_certs=ca_certs,
                      do_handshake_on_connect=do_handshake_on_connect, suppress_ragged_eofs=suppress_ragged_eofs,
                      ciphers=ciphers, curves=curves, sigalgs=sigalgs, user_mtu=user_mtu,
                      server_key_exchange_curve=None, server_cert_options=client_cert_options,
                      ssl_logging=ssl_logging, handshake_timeout=handshake_timeout)


def wrap_server(sock, keyfile=None, certfile=None,
                cert_reqs=ssl.CERT_NONE, ssl_version=ssl.PROTOCOL_DTLS, ca_certs=None,
                do_handshake_on_connect=False, suppress_ragged_eofs=True,
                ciphers=None, curves=None, sigalgs=None, user_mtu=None,
                server_key_exchange_curve=None, server_cert_options=ssl.SSL_BUILD_CHAIN_FLAG_NONE,
                ssl_logging=False, client_timeout=None, handshake_timeout=None,
                cb_ignore_ssl_exception_in_handshake=None, cb_ignore_ssl_exception_read=None,
                cb_ignore_ssl_exception_write=None):

    return DtlsSocket(sock=sock, keyfile=keyfile, certfile=certfile, server_side=True,
                      cert_reqs=cert_reqs, ssl_version=ssl_version, ca_certs=ca_certs,
                      do_handshake_on_connect=do_handshake_on_connect, suppress_ragged_eofs=suppress_ragged_eofs,
                      ciphers=ciphers, curves=curves, sigalgs=sigalgs, user_mtu=user_mtu,
                      server_key_exchange_curve=server_key_exchange_curve, server_cert_options=server_cert_options,
                      ssl_logging=ssl_logging, client_timeout=client_timeout, handshake_timeout=handshake_timeout,
                      cb_ignore_ssl_exception_in_handshake=cb_ignore_ssl_exception_in_handshake,
                      cb_ignore_ssl_exception_read=cb_ignore_ssl_exception_read,
                      cb_ignore_ssl_exception_write=cb_ignore_ssl_exception_write)


class DtlsSocket(object):

    class _ClientSession(object):

        def __init__(self, host, port, handshake_done=False, timeout=None):
            self.host = host
            self.port = int(port)
            self.handshake_done = handshake_done
            self.updateTimestamp()
            self.timeout = timeout

        def getAddr(self):
            return self.host, self.port

        def updateTimestamp(self):
            self.last_update = time.time()

        def expired(self):
            if self.timeout is None:
                return False
            else:
                return (time.time() - self.last_update) > self.timeout

    def __init__(
            self,
            sock=None,
            keyfile=None,
            certfile=None,
            server_side=False,
            cert_reqs=ssl.CERT_NONE,
            ssl_version=ssl.PROTOCOL_DTLSv1_2,
            ca_certs=None,
            do_handshake_on_connect=False,
            suppress_ragged_eofs=True,
            ciphers=None,
            curves=None,
            sigalgs=None,
            user_mtu=None,
            server_key_exchange_curve=None,
            server_cert_options=ssl.SSL_BUILD_CHAIN_FLAG_NONE,
            ssl_logging=False,
            client_timeout=None,
            handshake_timeout=None,
            cb_ignore_ssl_exception_in_handshake=None,
            cb_ignore_ssl_exception_read=None,
            cb_ignore_ssl_exception_write=None,
    ):

        if server_cert_options is None:
            server_cert_options = ssl.SSL_BUILD_CHAIN_FLAG_NONE

        self._ssl_logging = ssl_logging
        self._server_side = server_side
        self._ciphers = ciphers
        self._curves = curves
        self._sigalgs = sigalgs
        self._user_mtu = user_mtu
        self._server_key_exchange_curve = server_key_exchange_curve
        self._server_cert_options = server_cert_options
        self._client_timeout = client_timeout
        self._handshake_timeout = handshake_timeout
        self._cb_ignore_ssl_exception_in_handshake = cb_ignore_ssl_exception_in_handshake
        self._cb_ignore_ssl_exception_read = cb_ignore_ssl_exception_read
        self._cb_ignore_ssl_exception_write = cb_ignore_ssl_exception_write

        # Default socket creation
        if isinstance(sock, socket.socket):
            _sock = sock
        else:
            _sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        self._sock = ssl.wrap_socket(_sock,
                                     keyfile=keyfile,
                                     certfile=certfile,
                                     server_side=self._server_side,
                                     cert_reqs=cert_reqs,
                                     ssl_version=ssl_version,
                                     ca_certs=ca_certs,
                                     do_handshake_on_connect=do_handshake_on_connect,
                                     suppress_ragged_eofs=suppress_ragged_eofs,
                                     ciphers=self._ciphers,
                                     cb_user_config_ssl_ctx=self.user_config_ssl_ctx,
                                     cb_user_config_ssl=self.user_config_ssl)

        if self._server_side:
            self._clients = {}
            self._timeout = None

    def __getattr__(self, item):
        if hasattr(self, "_sock") and hasattr(self._sock, item):
            return getattr(self._sock, item)
        raise AttributeError

    def user_config_ssl_ctx(self, _ctx):
        """

        :param SSLContext _ctx:
        """
        _ctx.set_ssl_logging(self._ssl_logging)
        if self._ciphers:
            _ctx.set_ciphers(self._ciphers)
        if self._curves:
            _ctx.set_curves(self._curves)
        if self._sigalgs:
            _ctx.set_sigalgs(self._sigalgs)
        _ctx.build_cert_chain(flags=self._server_cert_options)
        if self._server_side:
            _ctx.set_ecdh_curve(curve_name=self._server_key_exchange_curve)

    def _dtls_timer_cb(self, ssl, timer_us):
        timer_us = 1000000  # Standard value from OpenSSL 1.1.1b
        if self._handshake_timeout:
            timer_us = int(self._handshake_timeout*1000*1000)
        _logger.debug("DTLS timer callback ... %d [us]", timer_us)
        return timer_us

    def user_config_ssl(self, _ssl):
        """

        :param SSL _ssl:
        """
        if self._user_mtu:
            _ssl.set_link_mtu(self._user_mtu)

        _ssl.DTLS_set_timer_cb(self._dtls_timer_cb)

    def settimeout(self, t):
        if self._server_side:
            self._timeout = t
        else:
            self._sock.settimeout(t)

    def close(self):
        if self._server_side:
            for cli in self._clients.keys():
                cli.close()
            self._sock.close()
        else:
            try:
                conn = self._sock.unwrap()
            except:
                pass
            else:
                conn.close()
            self._sock.close()

    def recvfrom(self, bufsize, flags=0):
        if self._server_side:
            return self._recvfrom_on_server_side(bufsize, flags=flags)
        else:
            return self._recvfrom_on_client_side(bufsize, flags=flags)

    def _recvfrom_on_server_side(self, bufsize, flags):
        while True:
            want_read = False
            try:
                r, _, x = select.select(self._getAllReadingSockets(), [], self._getAllReadingSockets(), self._timeout)

                if x:
                    _logger.critical("Exceptional conditions: %s", repr(x))

            except socket.timeout:
                # __Nothing__ received from any client
                pass

            except OSError as ose:
                import errno
                if ose.errno != errno.EBADF:
                    raise ose
                # Connection closed? Do nothing ...
                pass

            else:
                for conn in r:
                    _last_peer = None
                    try:
                        try:
                            _last_peer = conn.getpeername()
                        except:
                            pass

                        if self._sockIsServerSock(conn):
                            # Connect
                            want_read = self._clientAccept(conn)
                        else:
                            # Handshake
                            if not self._clientHandshakeDone(conn):
                                self._clientDoHandshake(conn)
                            # Normal read
                            else:
                                buf = self._clientRead(conn, bufsize)
                                if buf:
                                    self._clients[conn].updateTimestamp()
                                    if conn in self._clients:
                                        return buf, self._clients[conn].getAddr()
                                    else:
                                        _logger.warning('Received data from an already disconnected client!')

                    except Exception as e:
                        _logger.exception('Exception for connection %s %s raised: %s' % (repr(conn), repr(_last_peer), repr(e)))
                        if self._sockIsServerSock(conn) and e.errno == errno.EBADF:
                            _logger.critical("Bad file descriptor in server socket!")
                            raise e
                        setattr(e, 'peer', _last_peer)
                        if self._cb_ignore_ssl_exception_read is not None \
                          and isinstance(self._cb_ignore_ssl_exception_read, collections.Callable) \
                          and self._cb_ignore_ssl_exception_read(e):
                            self._clientDrop(conn, e)
                            continue
                        raise e

            try:
                for conn in self._getClientReadingSockets():
                    timeleft = conn.get_timeout()
                    if timeleft is not None and timeleft == 0:
                        ret = conn.handle_timeout()
                        _logger.debug('Retransmission triggered for %s: %d' % (str(self._clients[conn].getAddr()), ret))

                    if self._clients[conn].expired():
                        _logger.info('Found expired session (%s: %s)' % (repr(self._clients[conn].getAddr()), repr(conn)))
                        self._clientRemove(conn)

            except Exception as e:
                raise e

            if not want_read:
                break

        # __No_data__ received from any client
        raise socket.timeout

    def _recvfrom_on_client_side(self, bufsize, flags):
        try:
            buf = self._sock.recv(bufsize, flags)

        except ssl.SSLError as e:
            if e.errno == ssl.ERR_READ_TIMEOUT or e.args[0] == ssl.SSL_ERROR_WANT_READ:
                pass
            else:
                raise e

        else:
            if buf:
                return buf, self._sock.getpeername()

        # __No_data__ received from any client
        raise socket.timeout

    def sendto(self, buf, address):
        if self._server_side:
            return self._sendto_from_server_side(buf, address)
        else:
            return self._sendto_from_client_side(buf, address)

    def _sendto_from_server_side(self, buf, address):
        conn_found = None
        for conn, client in self._clients.items():
            if client.getAddr() == address:
                conn_found = conn
                break
        if conn_found:
            try:
                return self._clientWrite(conn_found, buf)
            except Exception as e:
                if self._cb_ignore_ssl_exception_write is not None \
                        and isinstance(self._cb_ignore_ssl_exception_write, collections.Callable) \
                        and self._cb_ignore_ssl_exception_write(e):
                    # self._clientDrop(conn_found, e)
                    return 0
                raise e
        return 0

    def _sendto_from_client_side(self, buf, address):
        try:
            if not self._sock._connected:
                self._sock.connect(address)
            bytes_sent = self._sock.send(buf)

        except ssl.SSLError as e:
            raise e

        return bytes_sent

    def _getClientReadingSockets(self):
        return [x for x in self._clients.keys()]

    def _getAllReadingSockets(self):
        return [self._sock] + self._getClientReadingSockets()

    def _sockIsServerSock(self, conn):
        return conn is self._sock

    def _clientHandshakeDone(self, conn):
        return conn in self._clients and self._clients[conn].handshake_done is True

    def _clientAccept(self, conn):
        _logger.debug('+' * 60)
        ret = None

        try:
            ret = conn.accept()
            _logger.info('Accept returned with ... %s' % (str(ret)))

        except Exception as e:
            raise e

        else:
            if ret:
                client, addr = ret
                host, port = addr
                if client in self._clients:
                    _logger.warning('Client already connected %s' % str(client))
                    raise ValueError
                client.setblocking(0)
                self._clients[client] = self._ClientSession(host=host, port=port, timeout=self._client_timeout)

                self._clientDoHandshake(client)

        return ret is None  # re-read?

    def _clientDoHandshake(self, conn):
        _logger.debug('-' * 60)
        # conn.setblocking(False)

        try:
            conn.do_handshake()
            _logger.info('Connection from %s successful' % (str(self._clients[conn].getAddr())))

            self._clients[conn].handshake_done = True

        except ssl.SSLError as e:
            if e.errno == ERR_HANDSHAKE_TIMEOUT or e.args[0] == ssl.SSL_ERROR_WANT_READ:
                pass
            else:
                self._clientDrop(conn, error=e)
                if self._cb_ignore_ssl_exception_in_handshake is not None \
                   and isinstance(self._cb_ignore_ssl_exception_in_handshake, collections.Callable) \
                   and self._cb_ignore_ssl_exception_in_handshake(e):
                    return
                raise e

    def _clientRead(self, conn, bufsize=4096):
        _logger.debug('*' * 60)
        ret = None

        try:
            ret = conn.recv(bufsize)
            _logger.info('From client %s ... bytes received %s' % (str(self._clients[conn].getAddr()), str(len(ret))))

        except ssl.SSLError as e:
            if e.args[0] == ssl.SSL_ERROR_WANT_READ:
                pass
            elif e.args[0] == ssl.SSL_ERROR_SSL and e.errqueue[0][0] == ERR_UNEXPECTED_MESSAGE:
                self._clientRemove(conn)
            else:
                self._clientDrop(conn, error=e)

        return ret

    def _clientWrite(self, conn, data):
        _logger.debug('#' * 60)
        ret = None

        try:
            _data = data
            ret = conn.send(_data)
            _logger.info('To client %s ... bytes sent %s' % (str(self._clients[conn].getAddr()), str(ret)))

        except Exception as e:
            raise e

        return ret

    def _clientDrop(self, conn, error=None):
        _logger.debug('$' * 60)

        if self._sockIsServerSock(conn):
            _logger.warning('Cannot drop server socket!')
            return

        client = None
        handshake_done = False
        addr = 'unkown'
        if conn in self._clients:
            client = self._clients.pop(conn)
            handshake_done = client.handshake_done
            addr = client.getAddr()

        try:
            if client is None:
                _logger.warning('Drop client %s not yet connected?!' % repr(conn))
            elif error:
                _logger.info('Drop client %s ... with error: %s' % (repr(addr), error))
            else:
                _logger.info('Drop client %s' % repr(addr))

            try:
                _conn = conn
                if handshake_done and conn.fileno():
                    _conn = conn.unwrap()
            except Exception as e:
                _logger.warning('Error in unwrap (%s): %s', repr(addr), e)
                conn.close()
            else:
                try:
                    _conn.close()
                except Exception as e:
                    _logger.info('Error in close (%s): %s', repr(addr), e)

        except Exception as e:
            _logger.warning('Error in clientDrop (%s): %s', repr(addr), e)
            pass

    def _clientRemove(self, conn):
        _logger.debug('$' * 60)

        if self._sockIsServerSock(conn):
            _logger.warning('Cannot remove server socket!')
            return

        addr = 'unkown'
        if conn in self._clients:
            client = self._clients.pop(conn)
            addr = client.getAddr()

        try:
            try:
                conn.close()
                _logger.info('Removed client: %s', repr(addr))

            except Exception as e:
                _logger.info('Error in close (%s): %s', repr(addr), e)

        except Exception as e:
            _logger.warning('Error in clientRemove (%s): %s', repr(addr), e)
