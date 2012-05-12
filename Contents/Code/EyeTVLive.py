# -*- encoding: utf8
#
# EyeTVLive.py - Plugin main class 
# Copyright (C) 2011 René Köcher <shirk@bitspin.org>
#
# This program is free software; you can redistribute it and/or modify it 
# under the terms of the GNU General Public License as published by the 
# Free Software Foundation; either version 2 of the License, or 
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but 
# WITHOUT ANY WARRANTY; without even the implied warranty of MERCHANTABILITY 
# or FITNESS FOR A PARTICULAR PURPOSE. 
# See the GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 59 Temple Place, Suite 330, Boston, MA 02111-1307 USA
#

import re
import time
import pickle
import socket

from EPGParser import EPGParser
from M3U8Parser import M3U8Parser
from TSStreamServer import TSStreamServer

from APIURLs import *

class EyeTVLive(object):
    VERSION = '0.1.0_beta3'
    
    def __init__(self):
        Log('EyeTVLive: __init__: Creating EyTVLive service..')
        
        Route.Connect('/video/eyetv-live/list/{mode}', self.gui_channel_list)
        Route.Connect('/video/eyetv-live/tune/{meta}', self.tune_to)
        Route.Connect('/video/eyetv-live/setup', self.gui_setup_menu)
        Route.Connect('/video/eyetv-live/setup/kickstart', self.kickstart)
        Route.Connect('/video/eyetv-live/setup/tokenscan', self.tokenscan)
        
        self.headers = {
            'User-Agent'          : 'EyeTV/1.2.3 CFNetwork/528.2 Darwin/11.0.0',
            'Accept'              : '*/*',
            'X-EyeConnect-Client' : 'iPhoneApp1',
            'X-EyeConnect-Token'  : '',
            'X-Device-Name'       : Prefs[PREFS_CLIENT],
            'X-App-UUID'          : '',
            'Accept-Encoding'     : 'gzip, deflate',
            'Connection'          : 'keep-alive',
        }

        self.local_connect = False
        self.lofi_version = False
        self.channel_list = []
        self.epg = EPGParser(self, '/video/eyetv-live')
        self.stream_base = ''

        self.validate_prefs(False)

        try:
            ObjectContainer(no_cache=True)
            self.old_style_menu=False
            Log.Info("EyeTVLive: __init__: Using new-style menus")
        except Framework.FrameworkException:
            self.old_style_menu=True
            Log.Info("EyeTVLive: __init__: Using old-style menus")
        
    def validate_prefs(self, force_valid=True):
        """
        Validate the user settings returning an error message if requested.
        """
        # invalidate the channel cache - switching between lofi / hifi could cause trouble
        self.channel_list = []
        self.headers = {
            'User-Agent'          : 'EyeTV/1.2.3 CFNetwork/528.2 Darwin/11.0.0',
            'Accept'              : '*/*',
            'X-EyeConnect-Client' : 'iPhoneApp1',
            'X-EyeConnect-Token'  : '',
            'X-Device-Name'       : Prefs[PREFS_CLIENT],
            'X-App-UUID'          : '',
            'Accept-Encoding'     : 'gzip, deflate',
            'Connection'          : 'keep-alive',
        }

        if Prefs[PREFS_LAIKA]:
            Log.Info('EyeTVLive: validate_prefs: Laika experimental features enabled')
        
        try:
            if Prefs[PREFS_DEVID] == 'IPAD':
                self.headers['User-Agent'] = 'EyeTV/1.2.3 CFNetwork/528.2 Darwin/11.0.0'
                self.headers['X-App-UUID'] = 'bb98c14885bb94442623ca1afe7b3912'
                Log.Info('EyeTVLive: validate_prefs: iPad client settings')
            elif Prefs[PREFS_DEVID] == 'IPHONE':
                self.headers['User-Agent'] = 'EyeTV/1.2.3 CFNetwork/485.13.9 Darwin/11.0.0'
                self.headers['X-App-UUID'] = '9735687db77159a0396d68a925433ec8'
                Log.Info('EyeTVLive: validate_prefs: iPhone client settings')
            else:
                self.headers['X-Safari']   = 'yes'
                Log.Info('EyeTVLive: validate_prefs: Safari client settings (PREFS_DEVID:"%s")' % Prefs[PREFS_DEVID])
            
            # first error will bail out
            if not Prefs[PREFS_HOST] or not Prefs[PREFS_PORT]:
                Log.Info('EyeTVLive: validate_prefs: host/port invalid')
                if force_valid:
                    raise RuntimeError(L('Invalid host/port configuration.'))
            try:
                v = long(Prefs[PREFS_PORT])
            except ValueError:
                Log.Info('EyeTVLive: validate_prefs: port is not numeric')
                if force_valid:
                    raise RuntimeError(L('Invalid port - value must be numeric.'))
                    
            # check for local connection (this needs improvement..)
            try:
                local_alias = ['127.0.0.1', 'localhost', socket.gethostname(), socket.getfqdn()]
                if Prefs[PREFS_HOST] in local_alias:
                    self.local_connect = True
                else:
                    self.local_connect = False
                
                if not self.local_connect:
                    # try to resolve the ip if it's a hostname
                    try:
                        ip = socket.gethostbyname(Prefs[PREFS_HOST])
                    except socket.error,e:
                        # it's either an ip or we couldn't resolve the hostname..
                        ip = Prefs[PREFS_HOST]
                    try:
                        # try to match the ip against all configured network ips
                        import commands
                        all_ips = commands.getoutput('/sbin/ifconfig | awk \'/inet6?/{ print $2 }\'')
                        
                        for if_ip in all_ips.split('\n'):
                            if ip == if_ip:
                                self.local_connect = True
                                break
                    except ImportError:
                        pass
                
                Log.Info("EyeTVLive: validate_prefs: local_connect=%d", self.local_connect)
            except socket.error, e:
                Log.Error("EyeTVLive: validate_prefs: could not determine local_connect: %s", e)
                self.local_connect = False
            
            # check this last as it's probably going to raise an "error"
            if Prefs[PREFS_TOKEN_TYPE] == 'prefs' and Prefs[PREFS_DEVID] != 'SAFARI':
                if not Prefs[PREFS_TOKEN] or not re.match('^[0-9a-fA-F]{32}', Prefs[PREFS_TOKEN]):
                    Log.Info('EyeTVLive: validate_prefs: TokenType "prefs" but no token set.')
                    self.lofi_version = True
                    if force_valid:
                        raise RuntimeError(L('No connect token specified.\n\nAdvanced features will be disabled.'))
                else:
                    self.lofi_version = False
                    self.headers['X-EyeConnect-Token'] = Prefs[PREFS_TOKEN]
            else:
                if not Dict[PREFS_TOKEN]:
                    Log.Info('EyeTVLive: validate_prefs: TokenType "scanning" but no token set.')
                    self.lofi_version = True
                    if force_valid:
                        raise RuntimeError(L('No connect token stored, please start the token scan.\n\nAdvanced features will be disabled'))
                else:
                    self.lofi_version = False
                    self.headers['X-EyeConnect-Token'] = Dict[PREFS_TOKEN]

            if Prefs[PREFS_DEVID] == 'SAFARI':
                Log('EyeTVLive: validate_prefs: forcing lofi_version for Safari client')
                self.lofi_version = True

            Log('EyeTVLive: validate_prefs: valid, lofi_version=%d', self.lofi_version)

        except RuntimeError, e:
            d = MessageContainer(L('Configuration Error'), str(e))
            return d
        finally:
            Dict[SERVICE_EXCHANGE] = String.Encode(pickle.dumps(
                {
                    'headers'      : dict(self.headers),
                    'lofi_version' : self.lofi_version
                }
            ))
            Dict.Save()

            self.epg.reset()
            self.channel_list = []

            URLService.NormalizeURL('x-eyetv-live-prefs://%s' % String.Encode(pickle.dumps(Dict[SERVICE_EXCHANGE])))

    def run_request(self, url, default=None, **kwargs):
        """
        Run a HTTP-Request returning parsed JSON data oder `default`
        """
        args = dict(kwargs)
        for k in [ PREFS_HOST, PREFS_PORT, PREFS_DEVID, PREFS_CLIENT ]:
            args[k] = Prefs[k]
        
        if not self.lofi_version:
            args[PREFS_TOKEN_TYPE] = Prefs[PREFS_TOKEN_TYPE]
            if PREFS_TOKEN_TYPE == 'prefs':
                args[PREFS_TOKEN] = Prefs[PREFS_TOKEN]
            else:
                args[PREFS_TOKEN] = Dict[PREFS_TOKEN]
        else:
            args[PREFS_TOKEN_TYPE] = ''
            args[PREFS_TOKEN] = ''
        
        try:
#            HTTP.ClearCache()
            if 'plain_http' in kwargs and kwargs['plain_http']:
                try:
                    res = HTTP.Request(url % args, headers=self.headers)
                except:
                    res = None
            else:
                res = JSON.ObjectFromURL(url % args, headers=self.headers)
            if not res:
                return default
            return res
        except Exception, e:
            Log.Error('EyeTVLive: run_request: failed: %s', e)
            return default

    def fetch_channel_list(self):
        """
        Fetch a complete channel list.
        If a connect token is available the list will contain basic EPG data.
        """
        if self.lofi_version:
            epg_detail = 0
        else:
            epg_detail = 2
        base = 0
        if self.channel_list:
            if epg_detail == 0:
                return self.channel_list
            
            need_refresh = False
            ts_now = self.epg.ts_unix_to_nsdate(time.time())
            for channel in self.channel_list:
                if not 'EPGData' in channel:
                    continue
                if not channel['EPGData']:
                    continue
                if channel['EPGData'][0]['STOPTIME'] < ts_now:
                    need_refresh = True
                    break
            if not need_refresh:
                Log('EyeTVLive: fetch_channel_list: Using cached channel list')
                return self.channel_list;
        
        Log('EyeTVLive: fetch_channel_list: Requesting channel list (detail=%d)', epg_detail)
        res = self.run_request(URL_CHANNEL_LIST, 
                               epg_detail=epg_detail,
                               item_base=base,
                               item_count=100)
        if not res:
            if self.channel_list:
                return self.channel_list
            self.channel_list = []
            return []
        total = res['total']
        data = []
        while total > 0:
            res = self.run_request(URL_CHANNEL_LIST, 
                                   epg_detail=epg_detail,
                                   item_base=base,
                                   item_count=100)
            if not res:
                break
            total = total - len(res['channelList'])
            base = base + len(res['channelList'])
            data.extend(res['channelList'])
 
#
#        if self.lofi_version:
#            data.sort(cmp=lambda x,y: int(x['displayNumber']) > int(y['displayNumber']))
#        else:
#            data.sort(cmp=lambda x,y: int(x['channelInfo']['displayNumber']) > int(y['channelInfo']['displayNumber']))
        self.channel_list = data
        Log('EyeTVLive: fetch_channel_list: Channel list has %d items' % len(self.channel_list))
        return data
    
    def tune_to(self, meta):
        if meta.startswith('INIT_ID_'):
            service_id = String.Decode(meta.replace('INIT_ID_', ''))
            Log('EyeTVLive: tune_to: INIT for service_id %s', service_id)
            try:
                kbps = long(Prefs[PREFS_KBPS])
            except:
                kbps = 2000

            if kbps < 320:
                kbps = 320
            elif kbps > 4540:
                kbps = 4540
            
            if self.lofi_version or Prefs[PREFS_CLIENT] == 'SAFARI':
                res = self.run_request(URL_TUNE_TO_SAFARI, kbps=kbps, service_id=service_id)
            else:
                res = self.run_request(URL_TUNE_TO_IDEV, kbps=kbps, service_id=service_id)
            
            if not res or not res['success']:
                Log.Debug('EyeTVLive: tune_to: channel-switch: #res %s', str(res))

                if not res:
                    d = MessageContainer(L('Internal error'), L('Failed to switch channels.'))
                else:
                    d = MessageContainer(L('Internal error'), L('Failed to switch channels.') + ' #errorcode: %d' % res['errorcode'])
                return d
            else:
                # wait until ready
                stream_url = res['m3u8URL']
                res = {1:True}
                Thread.Sleep(1.5) # don't hurry EyeTV..
                while res:
                    res = self.run_request(URL_READY)
                    if not res:
                        Log.Error('EyeTVLive: tune_to: empty response from EyeTV')
                        d = MessageContainer(L('Internal error'), L('EyeTV failed to switch channels.'))
                        return d

                    Log.Debug('EyeTVLive: tune_to: #res { %s }', str(res))
                    if res['isReadyToStream']:
                        if Prefs[PREFS_LAIKA]:
                            live_url = URL_STREAM_DIRECT % {
                                                    'service_id' : service_id,
                                                    'eyetv_live_host' : Prefs[PREFS_HOST], 
                                                    'eyetv_live_port' : Prefs[PREFS_PORT],
                                                    'stream_url' : stream_url
                                       }
                            Log.Debug('EyeTVLive: tune_to: stream is ready')

                            Response.Headers['Cache-Control'] = 'no-cache'
                            self.stream_base = '/'.join(stream_url.split('/')[:-1])
                            return Redirect(live_url)

                        else:
                            server = TSStreamServer(False,
                                                URL_STREAM % { 
                                                    'service_id' : service_id,
                                                    'eyetv_live_host' : Prefs[PREFS_HOST],
                                                    'eyetv_live_port' : Prefs[PREFS_PORT]
                                                }, stream_url)
                            if server.kickstart():
                                Response.Headers['Cache-Control'] = 'no-cache'
                                return Redirect('http://127.0.0.1:2171/stream.mpeg')
                            else:
                                d = MessageContainer(L('Internal error'), L('Failed to collect the stream.'))
                                return d
                    else:
                        Log.Debug('EyeTVLive: tune_to: buffering stream (%f/%f)..',
                                  res['doneEncoding'], res['minEncodingToStartStreaming'])
                        Thread.Sleep(1)

        elif meta.startswith('INIT_URL_'):
            meta = String.Decode(meta.replace('INIT_URL_', ''))
            self.stream_base = '/'.join(meta.split('/')[:-1])
            meta = '/'.join(stream_url.split('/')[-1])

            Log.Debug('EyeTVLive: tune_to: INIT from URLService: stream_base=%s', self.stream_base)

        return self.stream_proxy(meta)
    
    def stream_proxy(self, file):
        real_url = URL_STREAM % { 'eyetv_live_host' : Prefs[PREFS_HOST],
                                  'eyetv_live_port' : Prefs[PREFS_PORT]
                   }

        real_url += '/%s/%s' % (self.stream_base, file)
        return Redirect(real_url)
        
    def kickstart(self):
        d = MessageContainer('Kickstart','-')
        try:
            spawner = Helper.Process('SpawnEyeTV')
            spawner.wait()
            if spawner.returncode != 0:
                d.message = F('Failed to launch EyeTV: %d', spawner.returncode)
            else:
                d.message = F('EyeTV should be running now.')
        except Exception,e:
            d.message = F('Failed to launch EyeTV: %s', e)
        return d
    
    def tokenscan(self):
        d = MessageContainer('TokenScanner', '-')
        try:
            Log('EyeTVLive: tokenscan: Starting scanner on "%s"', Prefs[PREFS_SCANIF])
            scanner = Helper.Process('ScanToken.py', '-i', Prefs[PREFS_SCANIF], stderr=True)
            (out, err) = scanner.communicate()
            Log('EyeTVLive: tokenscan: Scanner out:\n%s\nEyeTVLive: Scanner err:\n%s\n', out, err)
            if scanner.returncode == 0:
                token=re.search('(?m).*([0-9a-fA-F]{32,32}).*', err)
                if token:
                    Dict[PREFS_TOKEN] = token.groups()[0]
                    d.message = F('Success!\nYour token is:\n%s', Dict[PREFS_TOKEN])
                    Dict['last_scan_on'] = '%s, %s' % (Prefs[PREFS_HOST], time.ctime())
                else:
                    d.message = L('Failed..\nNo token was scanned.')
            elif scanner.returncode == 2:
                d.message = L('Scanner terminated early - please try another network interface!')
            else:
                d.message = L('Failed..\nNo token was scanned.')
        except Exception, e:
            d.message = F('Failed..\nInternal error: %s', e)
        return d
    
    # -- gui code
    def gui_main_menu(self):
        """
        EyeTVLive main menu
        """
        if self.old_style_menu:
           # Use old-style classes for Plex < 0.9.3.4...
            d = MediaContainer(title1='EyeTVLive', no_cache=True)
            status = self.run_request(URL_STATUS)
            if self.local_connect and (not status or not status['isUp']):
                try:
                    Helper.Run('SpawnEyeTV')
                except Exception,e:
                    Log.Info('EyeTVLive: gui_main_menu: SpawnEyeTV failed: %s', e)
                status = self.run_request(URL_STATUS)
        
            if not status:
                d.title2= L('offline')
                d.header = L('Internal error')
                d.message = L('Could not connect to EyeTV!')
            elif not status['isUp']:
                d.title2= L('offline')
                d.header = L('Internal error')
                d.message = L('EyeTV is runnig but streaming is disabled.')
            else:
                d.title2='%s' % Prefs[PREFS_HOST]
                d.Append(DirectoryItem(
                    key = Callback(self.gui_channel_list, mode='channel'),
                    title = L('Channels')
                ))
                if not self.lofi_version:
                    d.Append(DirectoryItem(
                        key = Callback(self.gui_channel_list, mode='epg'),
                        title = L('EPG')
                    ))
            d.Append(DirectoryItem(
                key = Callback(self.gui_setup_menu),
                title = L('Setup')
            ))
        else:
            d = ObjectContainer(title1="EyeTVLive", view_group='Details', no_cache=True)
            status = self.run_request(URL_STATUS)
            if self.local_connect and (not status or not status['isUp']):
                try:
                    Helper.Run('SpawnEyeTV')
                except Exception,e:
                    Log.Info('EyeTVLive: gui_main_menu: SpawnEyeTV failed: %s', e)
                status = self.run_request(URL_STATUS)
        
            if not status:
                d.title2= L('offline')
                d.header = L('Internal error')
                d.message = L('Could not connect to EyeTV!')
            elif not status['isUp']:
                d.title2= L('offline')
                d.header = L('Internal error')
                d.message = L('EyeTV is runnig but streaming is disabled.')
            else:
                d.title2='%s' % Prefs[PREFS_HOST]
                d.add(DirectoryObject(
                    key = Callback(self.gui_channel_list, mode='channel'),
                    title = L('Channels')
                ))
                if not self.lofi_version:
                    d.add(DirectoryObject(
                        key = Callback(self.gui_channel_list, mode='epg'),
                        title = L('EPG')
                    ))
            d.add(DirectoryObject(
                key = Callback(self.gui_setup_menu),
                title = L('Setup')
            ))
        return d
    
    def gui_channel_list(self, mode):
        """
        Return the channel list menu either for channel selection or for EPG.
        """
        self.fetch_channel_list()
        if not self.channel_list:
            d = MessageContainer(L('Internal error'), L('Unable to fetch the channel list'))
            return d
        
        d = ObjectContainer(title2=L('Channels'), view_group='Details')
        for channel in self.channel_list:
            if self.lofi_version:
                info = channel
                epg = []
            else:
                info = channel['channelInfo']
                epg = channel.get('EPGData', [])
                
            if not info['name']:
                continue
            
            if epg:
                tagline = ' - %s' % (epg[0]['TITLE'])
                summary = '%s\n\n%s-%s %s\n"%s"\n\n' % (
                    L('Playing:'),
                    time.strftime('%H:%M', time.localtime(epg[0]['STARTTIME'])),
                    time.strftime('%H:%M', time.localtime(epg[0]['STOPTIME'])),
                    epg[0]['TITLE'],
                    epg[0]['ABSTRACT']
                )
                if len(epg) >= 2:
                    summary += '%s\n\n%s-%s %s\n' % (
                        L('Up next:'),
                        time.strftime('%H:%M', time.localtime(epg[1]['STARTTIME'])),
                        time.strftime('%H:%M', time.localtime(epg[1]['STOPTIME'])),
                        epg[1]['TITLE'],
                    )
                duration = (long(epg[0]['STOPTIME']) - long(epg[0]['STARTTIME'])) * 1000
            else:
                tagline = ''
                summary = L('<No details available>')
                duration = 1
            
            if mode == 'channel':
                d.add(VideoClipObject(
                      #url = HTTPLiveStreamURL(Callback(self.tune_to, meta='INIT_ID_%s' % String.Encode(info['serviceID']))),
                      key = Callback(self.tune_to, meta='INIT_ID_%s' % String.Encode(info['serviceID'])),
                      title = '%-4s %s%s' % (info['displayNumber'], info['name'], tagline),
                      summary = summary,
                      rating_key = info['serviceID']
                ))
            elif mode == 'epg':
                d.add(DirectoryObject(
                    key = self.epg.callback_for_channel(info['serviceID']),
                    title = '%-4s %s%s' % (info['displayNumber'], info['name'], tagline),
                    summary = summary
                ))
            else:
                return MessageContainer(L('Error'), L('Internal error..'))
        return d
    
    def gui_setup_menu(self, show_about=False):
        """
        Setup sub-menu, a place for tools and configuration..
        (and a clever hack to force the main menu to reload!)
        """
        if show_about:
            d = MessageContainer('EyeTVLive for Plex',
"""(c) 2012, some rights reserved
  Programming by Rene Koecher
Graphics design by Peter Flaherty
""")
            return d
        
        d = ObjectContainer(title1=L('Settings'), view_group='Details')

        if 'last_scan_on' in Dict:
            scan_info = Dict['last_scan_on']
        else:
            scan_info = L('never')
        
        d.add(DirectoryObject(
            key = Callback(self.tokenscan), 
            title = L('Scan for connection token'),
            summary = F("""
This will launch the tokenscanner 
which will listen to your local network (%s).

After selecting the item please use your
iPhone/Pad/Pod and browse the EPG of the
desired EyeTV.

Last Scan: %s

NOTE: This will only work for EyeTV an LAN or on the same machine as Plex!""",
            Prefs[PREFS_SCANIF], scan_info),
        ))
        
        if self.local_connect:
            d.add(DirectoryObject(
                key = Callback(self.kickstart), 
                title = L('Start EyeTV'),
                summary = L("""
Try to start the local EyeTV in server mode.
(This works only if Plex and EyeTV are on the some machine)
""")
            ))
        else:
            d.add(DirectoryObject(
                key = Callback(self.gui_setup_menu),
                title = L('(Local tools are disabled)')
            ))
        d.add(PrefsObject(title=L('Preferences')))
        d.add(DirectoryObject(key = Callback(self.gui_setup_menu), title=''))
        d.add(DirectoryObject(
            key = Callback(self.gui_setup_menu, show_about=True),
            title='About',
            summary = """         EyeTVLive for Plex
     Programming by Rene Koecher (c) 2012
 Graphics Design by Peter Flaherty (c) 2012
--------------------------------------------
EyeTV live core: %s
      EPGParser: %s
     M3U8Parser: %s
 TSStreamServer: %s
--------------------------------------------
""" % (EyeTVLive.VERSION, EPGParser.VERSION, M3U8Parser.VERSION, TSStreamServer.VERSION)
        ))
        return d
        