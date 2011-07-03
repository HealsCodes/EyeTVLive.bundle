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
import socket

from EPGParser import EPGParser
from TSStreamServer import TSStreamServer

PREFS_HOST         = 'eyetv_live_host'
PREFS_PORT         = 'eyetv_live_port'
PREFS_DEVID        = 'eyetv_live_devid'
PREFS_CLIENT       = 'eyetv_live_client'
PREFS_TOKEN        = 'eyetv_live_token'
PREFS_TOKEN_TYPE   = 'eyetv_live_token_type'
PREFS_SCANIF       = 'eyetv_live_scanif'

BASE_URL           = 'http://%(eyetv_live_host)s:%(eyetv_live_port)s'
URL_STATUS         = BASE_URL + '/live/status/0/_%(eyetv_live_devid)s_MAINMENU'
URL_SEED           = BASE_URL + '/live/seed/0'
URL_STREAM         = BASE_URL + '/live/stream'
URL_TIMEZONE       = BASE_URL + '/live/timeZone/0'
URL_FAVORITES      = BASE_URL + '/live/favorites/0/_%(eyetv_live_devid)s_FAVORITES'
URL_CHANNEL_LIST   = BASE_URL + '/live/channels/%(epg_detail)d/0/%(item_base)d/%(item_count)d/_%(eyetv_live_devid)s_CHANNELS'
URL_TUNE_TO_SAFARI = BASE_URL + '/live/tuneto/1/%(kbps)d/%(service_id)s/_SAFARI_PLAYER'
URL_TUNE_TO_IDEV   = BASE_URL + '/live/tuneto/1/%(kbps)d/0/1/6/%(service_id)s/_%(eyetv_live_devid)s_PLAYER'
URL_READY          = BASE_URL + '/live/ready/0/_%(eyetv_live_devid)s_PLAYER'
#URL_RECORD_SET     = BASE_URL + '/live/schedule/1/%(show_uuid)s/%(service_id)s/_%(eyetv_live_devid)s_DETAILS'
#URL_RECORD_DEL     = BASE_URL + '/live/deleteschedule/0/%(ts_start)s/_%(eyetv_live_devid)s_DETAILS'
URL_EPG_REQUEST    = BASE_URL + '/epg/request/0/%(ts_start)d/%(ts_end)d/%(service_id)s/_%(eyetv_live_devid)s_EPG'
URL_EPG_SHOW_INFO  = BASE_URL + '/epg/info/1/%(show_uuid)s/_%(eyetv_live_devid)s_EPG'

class EyeTVLive(object):
    def __init__(self):
        Log('Creating EyTVLive service..')
        
        Route.Connect('/video/eyetv-live/list/{mode}', self.gui_channel_list)
        Route.Connect('/video/eyetv-live/tune/{service_id}/{kbps}', self.tune_to)        
        Route.Connect('/video/eyetv-live/setup', self.gui_setup_menu)
        Route.Connect('/video/eyetv-live/setup/kickstart', self.kickstart)
        Route.Connect('/video/eyetv-live/setup/tokenscan', self.tokenscan)
        
        self.headers = {
            'User-Agent'          : 'EyeTV/1.2.3 CFNetwork/528.2 Darwin/11.0.0',
            'Accept'              : '*/*',
            'X-EyeConnect-Client' : 'iPhoneApp1',
            'X-EyeConnect-Token'  : '',
            'X-Device-Name'       : Prefs[PREFS_CLIENT],
            'Accept-Encoding'     : 'gzip, deflate',
            'Connection'          : 'keep-alive',
        }
        self.local_connect = False
        self.lofi_version = False
        self.channel_list = []
        self.epg = EPGParser(self, '/video/eyetv-live', URL_EPG_REQUEST, URL_EPG_SHOW_INFO)        
        
        self.validate_prefs(False)
        
    def validate_prefs(self, force_valid=True):
        """
        Validate the user settings returning an error message if requested.
        """
        try:
            # first error will bail out
            if not Prefs[PREFS_HOST] or not Prefs[PREFS_PORT]:
                Log.Info('EyeTV: validate_prefs: host/port invalid')
                if force_valid:
                    raise RuntimeError(L('Invalid host/port configuration.'))
            try:
                v = long(Prefs[PREFS_PORT])
            except ValueError:
                Log.Info('EyeTV: validate_prefs: port is not numeric')
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
                
                Log.Info("EyeTV: validate_prefs: local_connect=%d", self.local_connect)
            except socket.error, e:
                Log.Error("EyeTV: validate_prefs: could not determine local_connect: %s", e)
                self.local_connect = False
            
            # check this last as it's probably going to raise an "error"
            if Prefs[PREFS_TOKEN_TYPE] == 'prefs':
                if not Prefs[PREFS_TOKEN] or not re.match('^[0-9a-fA-F]{32}', Prefs[PREFS_TOKEN]):
                    Log.Info('EyeTV: validate_prefs: TokenType "prefs" but no token set.')
                    self.lofi_version = True
                    self.epg.reset()
                    self.channel_list = []
                    if force_valid:
                        raise RuntimeError(L('No connect token specified.\n\nAdvanced features will be disabled.'))
                else:
                    self.lofi_version = False
                    self.headers['X-EyeConnect-Token'] = Prefs[PREFS_TOKEN]
            else:
                if not Dict[PREFS_TOKEN]:
                    Log.Info('EyeTV: validate_prefs: TokenType "scanning" but no token set.')
                    self.lofi_version = True
                    self.epg.reset()
                    self.channel_list = []
                    if force_valid:
                        raise RuntimeError(L('No connect token stored, please start the token scan.\n\nAdvanced features will be disabled'))
                else:
                    self.lofi_version = False
                    self.headers['X-EyeConnect-Token'] = Dict[PREFS_TOKEN]
            Log('EyeTV: validate_prefs: valid, lofi_version=%d', self.lofi_version)
        except RuntimeError, e:
            d = MessageContainer(L('Configuration Error'), str(e))
            return d
    
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
                Log('Using cached channel list')
                return self.channel_list;
        
        Log('EyeTVLive: Requesting channel list (detail=%d)', epg_detail)
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
        Log('EyeTVLive: Channel list has %d items' % len(self.channel_list))
        return data
    
    def tune_to(self, service_id, kbps):
        """
        Tune to `service_id` and redirect to the running stream if possible.
        """
        if kbps < 320:
            kbps = 320
        elif kbps > 2000:
            kbps = 2000
        if self.lofi_version or Prefs[PREFS_CLIENT] == 'SAFARI':
            res = self.run_request(URL_TUNE_TO_SAFARI, kbps=kbps, service_id=service_id)
        else:
            res = self.run_request(URL_TUNE_TO_IDEV, kbps=kbps, service_id=service_id)
        if not res or not res['success']:
            d = MessageContainer(L('Internal error'), L('Failed to switch channels.'))
            return d
        else:
            # wait until ready
            stream_url = res['m3u8URL']
            res = {1:True}
            while res:
                res = self.run_request(URL_READY)
                if not res:
                    d = MessageContainer(L('Internal error'), L('EyeTV failed to switch channels.'))
                    return d
                if res['isReadyToStream']:
                    Log.Debug('EyeTVLive: stream is ready, manifesting server..')
                    server = TSStreamServer(URL_STREAM % { 
                                                'service_id' : service_id,
                                                'eyetv_live_host' : Prefs[PREFS_HOST],
                                                'eyetv_live_port' : Prefs[PREFS_PORT]
                                            }, stream_url)
                    if server.kickstart():
                        return Redirect('http://127.0.0.1:2171/stream.mpeg')
                    else:
                        d = MessageContainer(L('Internal error'), L('Failed to collect the stream.'))
                        return d
                else:
                    Log.Debug('EyeTVLive: buffering stream (%f/%f)..',
                              res['doneEncoding'], res['minEncodingToStartStreaming'])
                    Thread.Sleep(1)
    
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
            Log('EyeTVLive: Starting scanner on "%s"', Prefs[PREFS_SCANIF])
            scanner = Helper.Process('ScanToken.py', '-i', Prefs[PREFS_SCANIF], stderr=True)
            (out, err) = scanner.communicate()
            Log('EyeTVLive: Scanner out:\n%s\nEyeTVLive: Scanner err:\n%s\n', out, err)
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
        EyeTV live main menu
        """
       # Use old-style classes until ObjectContainer acquires no_cache..
        d = MediaContainer(title1='EyeTV', no_cache=True)
        status = self.run_request(URL_STATUS)
        if self.local_connect and (not status or not status['isUp']):
            try:
                Helper.Run('SpawnEyeTV')
            except Exception,e:
                Log.Info('SpawnEyeTV failed: %s', e)
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

#        d = ObjectContainer(title1="EyeTV", view_group='Category')
#        status = self.run_request(URL_STATUS)
#        if self.local_connect and (not status or not status['isUp']):
#            try:
#                Helper.Run('SpawnEyeTV')
#            except Exception,e:
#                Log.Info('SpawnEyeTV failed: %s', e)
#            status = self.run_request(URL_STATUS)
#        
#        if not status:
#            d.title2='offline'
##            d.add(MessageContainer('Internal error', 'Could not connect to EyeTV!'))
#        elif not status['isUp']:
#            d.title2='offline'
##            d.add(MessageContainer('Internal error', 'EyeTV is running but streaming is disabled.'))
#        else:
#            d.title2='%s' % Prefs[PREFS_HOST]
##            d.add(MessageContainer('Success', 'We\'re live!'))
#            d.add(DirectoryObject(
#                key = Callback(self.gui_channel_list, mode='channel'),
#                title ='Channels'
#            ))
#            if not self.lofi_version:
#                d.add(DirectoryObject(
#                    key = Callback(self.gui_channel_list, mode='epg'),
#                    title = 'EPG'
#                ))
#        d.add(DirectoryObject(
#            key = Callback(self.gui_setup_menu),
#            title = 'Setup'
#        ))
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
                summary = ''
                duration = 1
            
            if mode == 'channel':
                k = Callback(self.tune_to, service_id=info['serviceID'], kbps=20000)
            elif mode == 'epg':
                k = self.epg.callback_for_channel(info['serviceID'])
            else:
                k = Callback(self.gui_main_menu, service_id=info['serviceID'])
            
            if mode == 'channel':
                d.add(VideoClipObject(
                      key = k,
                      title = '%-4s %s%s' % (info['displayNumber'], info['name'], tagline),
                      summary = summary
#                      ,items = [
#                        MediaObject(
#                          parts = [
#                            PartObject(key=k)
#                          ],
#                          protocols = [Protocol.HTTPLiveStreaming],
#                          protocols = [Protocol.HTTPMP4Video, Protocol.HTTPVideo, Protocol.HTTPMP4Streaming],
#                          platforms = [ClientPlatform.MacOSX],
#                          video_codec = VideoCodec.H264,
#                          audio_codec = AudioCodec.AAC
#                        )
#                      ]
                ))
            else:
                d.add(DirectoryObject(
                    key = k,
                    title = '%-4s %s%s' % (info['displayNumber'], info['name'], tagline),
                    summary = summary
                ))
        return d
    
    def gui_setup_menu(self):
        """
        Setup sub-menu, a place for tools and configuration..
        (and a clever hack to force the main menu to reload!)
        """
        d = ObjectContainer(title1=L('Settings'))
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
        return d
        