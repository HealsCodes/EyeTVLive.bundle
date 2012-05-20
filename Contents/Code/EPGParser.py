# -*- encoding: utf8
#
# EPGParser.py  - Parse JSON EPG data and return MediaItems
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

import time

from APIURLs import *

class EPGParser(object):
    VERSION = '0.3'
    
    def __init__(self, request_delegate, base_url):
        Route.Connect(base_url + '/epg/show/{service_id}', self.gui_epg_for_channel)
        Route.Connect(base_url + '/epg/show/{service_id}/{uniqueid}', self.gui_epg_for_show)
        Route.Connect(base_url + '/epg/record/del/{service_id}/{uniqueid}/{rec_id}', self.cancel_recording)
        Route.Connect(base_url + '/epg/record/set/{service_id}/{uniqueid}/{rec_id}', self.schedule_recording)
        
        self.epg_start = 0
        self.epg_end = 0
        self.epg_channel_data = {}
        self.epg_detail_data = {}
        self.epg_recordings_data = {}
        self.epg_lock = Thread.Lock()
        self.delegate = request_delegate

    def run_request(self, url, **kwargs):
        return self.delegate.run_request(url, **kwargs)
    
    def reset(self):
        """
        Clean the EPG cache
        """
        self.epg_channel_data = {}
        self.epg_detail_data = {}
        self.epg_recordings_data = {}
    
    def compact_cache(self):
        """
        Compact the uuid cache removing expired entries.
        """
        ts_now = self.ts_unix_to_nsdate(time.time())
        if not self.epg_lock.acquire(False):
            Log.Info('EPGParser: not compacting cache, it\'s locked')
            return
        # -- critical section --
        expired = []
        for uuid in self.epg_detail_data:
            if self.epg_detail_data[uuid]['STOPTIME'] >= ts_now:
                expired.append(uuid)
        for uuid in expired:
            self.epg_detail_data.pop(uuid)
            if uuid in self.epg_recordings_data:
                self.epg_recordings_data.pop(uuid)
        # -- end critical section --        
        self.epg_lock.release()
        if expired:
            Log.Info('EPGParser: compacted cache by removing %d items', len(expired))
    
    
    def fetch_channel_data(self, service_id, skip_cache=False):
        """
        Fetch the cannel data for the next 24 hours for a given service_id.
        Data will be cached on a per channel basis with one hour expiration time.
        """
        t = time.time()
        ts_now = self.ts_unix_to_nsdate(time.time())
        ts_end = ts_now + 86400
        if service_id in self.epg_channel_data and self.epg_start - ts_now < 3600:
            if not skip_cache:
                Log.Debug('EPGParser: using cached channel data (younger than 1 hour)')
                return True
        
        # -- critical section --
        if not self.epg_lock.acquire(False):
            Log.Info('EPGParser: using cached channel data, EPG is locked')
        else:
            epg_data = self.run_request(URL_EPG_REQUEST,
                                        ts_start=ts_now - 86400,
                                        ts_end=ts_end,
                                        service_id=service_id)
            if not epg_data:
                Log.Error('EPGParser: Request for service_id=%s failed', service_id)
                self.epg_lock.release()
                return False
            else:
                Log.Info('EPGParser: cached service_id=%s (%s -> %s)',
                         service_id,
                         time.strftime('%D %R', time.localtime(ts_now)),
                         time.strftime('%D %R', time.localtime(ts_end)))
                self.epg_start = ts_now
                self.epg_end = ts_end
                self.epg_channel_data[service_id] = epg_data
                self.epg_lock.release()
                return True
        # -- end critical section --
    
    def fetch_detail_data(self, service_id, uniqueid):
        """
        Fetch detailed show info for a given uniqueid.
        (Will return cached hits where possible)
        """
        if uniqueid in self.epg_detail_data:
            self.epg_lock.acquire()
            # -- critical section --
            epg_data = [self.epg_detail_data[uniqueid]]
            record_data = self.run_request(URL_RECORD_GET, show_uuid=uniqueid, 
                                                           show_starttime=epg_data[0]['STARTTIME'],
                                                           show_stoptime=epg_data[0]['STOPTIME'],
                                                           service_id=service_id)
            if not record_data:
                Log.Error('EPGParser: Request for record_data for uniqueid=%s failed', uniqueid)
                # FIXME: bail out or keep going? - for now, keep going
            else:
                self.epg_recordings_data[uniqueid] = record_data

            self.epg_lock.release()
            # -- end critical section --
            return self.epg_detail_data[uniqueid]
        self.epg_lock.acquire()
        # -- critical section --
        epg_data = self.run_request(URL_EPG_SHOW_INFO, show_uuid=uniqueid)
        if not epg_data:
            Log.Error('EPGParser: Request for uniqueid=%s failed', uniqueid)
            self.epg_lock.release()
            return None
        self.epg_detail_data[uniqueid] = epg_data[0]
        
        record_data = self.run_request(URL_RECORD_GET, show_uuid=uniqueid, 
                                                       show_starttime=epg_data[0]['STARTTIME'],
                                                       show_stoptime=epg_data[0]['STOPTIME'],
                                                       service_id=service_id)
        if not record_data:
            Log.Error('EPGParser: Request for record_data for uniqueid=%s failed', uniqueid)
            # FIXME: bail out or keep going? - for now, keep going
        else:
            self.epg_recordings_data[uniqueid] = record_data
        self.epg_lock.release()
        # -- end critical section --
        return self.epg_detail_data[uniqueid]
    
    def filter_data(self, data):
        """
        Return a filtered version of `data` containing only EPG items on air
        or in the future.
        """
        ts_now = self.ts_unix_to_nsdate(time.time())
        epg_data = []
        for show in data:
            if ts_now < show['STOPTIME']:
#                Log.Debug('EPGParser: +++ "%s" (%d < %d)', show['TITLE'], ts_now, show['STOPTIME'])
                epg_data.append(show)
#            else:
#                Log.Debug('EPGParser: --- "%s" (%d < %d)', show['TITLE'], ts_now, show['STOPTIME'])
        Log.Info('EPGParser: filtered data contains %d out of %d items', len(epg_data), len(data))
        return epg_data
    
    def format_detail_data(self, service_id, show):
        """
        Return a dict with pre-formated EPG data for a given show.
        """
        detail = self.fetch_detail_data(service_id, show['UNIQUEID'])
        if detail:
             duration = time.strftime('%H:%M', time.localtime(-3600 + (detail.get('STOPTIME', 0) - detail.get('STARTTIME', 0)))) 
             summary = '%s\n%s\n%s\n\n%s\n\n%s\n%s\n%s %s' % (
                 detail.get('ABSTRACT', '-'),
                 duration,
                 time.strftime('%c', time.localtime(self.ts_nsdate_to_unix(show['STARTTIME']))),
                 detail.get('DESCRIPTION', '-'),
                 L('Director: ') + detail.get('DIRECTOR', '-'),
                 L('Actors: ') + detail.get('OTHERS', '-'),
                 L('Produced in: ') + detail.get('COUNTRY', '-'),
                 detail.get('YEAR', '')
             )
        else:
            summary = L('<No details available>')
        
        title = show['TITLE']
        if show['UNIQUEID'] in self.epg_recordings_data:
            record_id = self.epg_recordings_data[show['UNIQUEID']]['programID']
            if not record_id == 0:
                title = '%s [REC]' % (show['TITLE'])
        else:
            record_id = 0
            
        title = '%s-%s %s' % (
            time.strftime('%H:%M', time.localtime(show['STARTTIME'])),
            time.strftime('%H:%M', time.localtime(show['STOPTIME'])),
            title
        )
        tagline = show['ABSTRACT']
        summary = summary
        duration = (long(show['STOPTIME']) - long(show['STARTTIME'])) * 1000

        res = { 'title':title, 'tagline':tagline, 'summary':summary, 'duration':duration, 'rec':record_id }
        for k in res:
            if isinstance(res[k], str):
                try:
                    res[k] = unicode(res[k].decode('iso8859-15'))
                except UnicodeDecodeError:
                    res[k] = unicode(res[k].decode(errors='ignore'))

        return res
    
    def schedule_recording(self, service_id, uniqueid, rec_id):
        """
        Schedule a show for recording
        """
        res = self.run_request(URL_RECORD_SET, show_uuid=uniqueid,
                                               service_id=service_id)
        if not res:
            return MessageContainer(L('Error'), L('Unable to cancel the recording!'))
        self.epg_recordings_data[uniqueid] = res
        self.fetch_channel_data(service_id, skip_cache=True)
        return MessageContainer(L('OK'), L('Scheduled for record.'))

    def cancel_recording(self, service_id, uniqueid, rec_id):
        """
        Cancel a scheduled recording
        """
        res = self.run_request(URL_RECORD_DEL, default=True, show_reckey=rec_id, plain_http=True)
        if not res:
            return MessageContainer(L('Error'), L('Recording failed!'))
        self.epg_recordings_data[uniqueid] = {}
        self.fetch_channel_data(service_id, skip_cache=True)
        return MessageContainer(L('OK'), L('Recording canceled.'))
        
    def ts_unix_to_nsdate(self, seconds):
        """
        Given the current seconds since epoch return a dst-adjusted NSDate version
        """
        try:
            ts = time.localtime(seconds)
            if ts.tm_isdst == 1:
                seconds = seconds - 3600
            return long(seconds - time.mktime(time.strptime('1.1.2001', '%d.%m.%Y')))
        except Exception, e:
            Log.Debug("Error: %s", e)
            return 0
    
    
    def ts_nsdate_to_unix(self, seconds):
        """
        Given a timestamp in seconds since NSDate-Epoch return a dst-adjusted timestamp
        """
        if time.localtime().tm_isdst == 1:
            seconds = seconds + 3600
        return long(seconds + time.mktime(time.strptime('1.1.2001', '%d.%m.%Y')))
    
    
    def callback_for_channel(self, service_id):
        """
        Retun a Callback bound to a specific service_id
        """
        return Callback(self.gui_epg_for_channel, service_id=service_id)
    
    def gui_epg_for_channel(self, service_id):
        """
        Generate the EPG guide for a given service_id.
        """
        if self.fetch_channel_data(service_id):
            self.epg_lock.acquire()
            channel_data = self.epg_channel_data[service_id][0]
            self.epg_lock.release()
            
            self.compact_cache()
            d = ObjectContainer(title2 = channel_data['channelInfo']['name'], view_group='Category')
            for show in self.filter_data(channel_data['EPGData']):
                detail = self.format_detail_data(service_id, show)
                s = DirectoryObject(
                    key = Callback(self.gui_epg_for_show, service_id=service_id, uniqueid=show['UNIQUEID']),
                    title = detail['title'],
                    tagline = detail['tagline'],
                    summary = detail['summary'],
                    duration = detail['duration']
                )
                d.add(s)
            return d
        else:
            d = MessageContainer(L('Error'), L('Unable to fetch EPG data.'))
        return d
    
    def gui_epg_for_show(self, service_id, uniqueid):
        self.epg_lock.acquire()
        channel_data = self.epg_channel_data[service_id][0]
        self.epg_lock.release()
        show_dict = dict([(str(x['UNIQUEID']), x) for x in self.filter_data(channel_data['EPGData'])])
        if not uniqueid in show_dict:
            return MessageContainer(L('Error'), L('Unable to fetch EPG data.'))
        
        show = show_dict[uniqueid]
        detail = self.format_detail_data(service_id, show)
        d = ObjectContainer(title2=L('EPG details'), view_group='Details')
        d.add(DirectoryObject(
                key = Callback(self.gui_epg_for_show, service_id=service_id, uniqueid=uniqueid),
                title = detail['title'],
                tagline = detail['tagline'],
                summary = detail['summary'],
                duration = detail['duration']
        ))
        d.add(VideoClipObject(
                key = Callback(self.delegate.tune_to, meta='INIT_ID_%s' % String.Encode(service_id)),
                rating_key = service_id,
                title = F('Watch %s', channel_data['channelInfo']['name']),
        ))
        if detail['rec']:
            d.add(DirectoryObject(
                    key = Callback(self.cancel_recording, service_id=service_id, uniqueid=uniqueid, rec_id=detail['rec']),
                    title = L('Cancel Recording'),
                    summary = L('Cancel the scheduled recording for this show.')
            ))
        else:
            d.add(DirectoryObject(
                    key = Callback(self.schedule_recording, service_id=service_id, uniqueid=uniqueid, rec_id=detail['rec']),
                    title = L('Record'),
                    summary = L('Schedule this show for recording.')
            ))
        return d
    
