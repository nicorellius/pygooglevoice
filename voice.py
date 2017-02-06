from googlevoice.conf import config
from googlevoice.util import *
import googlevoice.settings as settings
import os

if settings.DEBUG:
    import logging
    logging.basicConfig()
    log = logging.getLogger('PyGoogleVoice')
    log.setLevel(logging.DEBUG)
else:
    log = None


class Voice(object):
    """
    Main voice instance for interacting with the Google Voice service
    Handles login/logout and most of the baser HTTP methods
    """
    def __init__(self):
        install_opener(build_opener(HTTPCookieProcessor(CookieJar())))
        self._special = None
        self._contacts = None

        for name in settings.FEEDS:
            setattr(self, name, self.__get_xml_page(name))
        
    # Some handy methods
    def special(self):
        """
        Returns special identifier for your session (if logged in)
        """
        if hasattr(self, '_special') and getattr(self, '_special'):
            return self._special
        try:
            try:
                regex = bytes("('_rnr_se':) '(.+)'", 'utf8')
            except TypeError:
                regex = bytes("('_rnr_se':) '(.+)'")
        except NameError:
            regex = r"('_rnr_se':) '(.+)'"
        try:
            content = urlopen(settings.INBOX).read()
            sp = re.search(regex, content).group(2)
        except AttributeError:
            sp = None
        self._special = sp
        return sp
    special = property(special)
    
    def login(self, email=None, passwd=None):
        """
        Login to the service using your Google Voice account
        Credentials will be prompted for if not given as args or in the ``~/.gvoice`` config file
        """
        if hasattr(self, '_special') and getattr(self, '_special'):
            return self
        
        if email is None:
            email = config.email
        if email is None:
            email = input('Email address: ')
        
        if passwd is None:
            passwd = config.password
        if passwd is None:
            from getpass import getpass
            passwd = getpass()

        content = self.__do_page('login').read()
        # holy hack job
        galx = re.search(b"type=\"hidden\" name=\"GALX\" *value=\"(.+)\"", content).group(1)
        gxf = re.search(b"type=\"hidden\" name=\"gxf\" *value=\"(.+)\"", content).group(1)
        service = re.search(b"type=\"hidden\" name=\"service\" value=\"(.+)\"", content).group(1)
        utf8b = b"type=\"hidden\" id=\"_utf8\" name=\"_utf8\" value=\"(.+)\""
        utf8 = re.search(utf8b, content).group(1)
        bgresponseb = b"type=\"hidden\" name=\"bgresponse\" id=\"bgresponse\" value=\"(.+)\""
        bgresponse = re.search(bgresponseb, content).group(1)
        pstmsg = "1"

        self.__do_page('login', {'Email': email, 
                                 'Passwd': passwd, 
                                 'GALX': galx,
                                 'gxf': gxf,
                                 '_utf8': utf8, 
                                 'bgresponse': bgresponse, 
                                 'pstMsg': pstmsg,
                                 'service': service, 
                                 'continue': 'https://www.google.com/voice/', 
                                 'followup': 'https://www.google.com/voice/'})
        
        del email, passwd
        
        try:
            assert self.special
        except (AssertionError, AttributeError):
            raise LoginError

        return self
        
    def logout(self):
        """
        Logs out an instance and makes sure it does not still have a session
        """
        self.__do_page('logout')
        del self._special 
        assert self.special is None
        return self
        
    def call(self,
             outgoing_number,
             forwarding_number=None,
             phone_type=None,
             subscriber_number=None):
        """
        Make a call to an ``outgoingNumber`` from your ``forwardingNumber`` (optional).
        If you pass in your ``forwardingNumber``, please also pass in the correct ``phoneType``
        """        
        if forwarding_number is None:
            forwarding_number = config.forwardingNumber
        if phone_type is None:
            phone_type = config.phoneType
            
        self.__validate_special_page('call', {
            'outgoingNumber': outgoing_number,
            'forwardingNumber': forwarding_number,
            'subscriberNumber': subscriber_number or 'undefined',
            'phoneType': phone_type,
            'remember': '1'
        })
        
    __call__ = call
    
    def cancel(self, outgoing_number=None, forwarding_number=None):
        """
        Cancels a call matching outgoing and forwarding numbers (if given). 
        Will raise an error if no matching call is being placed
        """
        self.__validate_special_page('cancel', {
            'outgoingNumber': outgoing_number or 'undefined',
            'forwardingNumber': forwarding_number or 'undefined',
            'cancelType': 'C2C',
        })

    def phones(self):
        """
        Returns a list of ``Phone`` instances attached to your account.
        """
        return [Phone(self, data) for data in self.contacts['phones'].values()]
    phones = property(phones)

    def settings(self):
        """
        Dict of current Google Voice settings
        """
        return AttrDict(self.contacts['settings'])
    settings = property(settings)
    
    def send_sms(self, phone_number, text):
        """
        Send an SMS message to a given ``phoneNumber`` with the given ``text`` message
        """
        self.__validate_special_page('sms', {'phoneNumber': phone_number, 'text': text})

    def search(self, query):
        """
        Search your Google Voice Account history for calls, voicemails, and sms
        Returns ``Folder`` instance containing matching messages
        """
        return self.__get_xml_page('search', data='?q=%s' % quote(query))()
        
    def download(self, msg, adir=None):
        """
        Download a voicemail or recorded call MP3 matching the given ``msg``
        which can either be a ``Message`` instance, or a SHA1 identifier. 
        Saves files to ``adir`` (defaults to current directory). 
        Message hashes can be found in ``self.voicemail().messages`` for example. 
        Returns location of saved file.
        """
        from os import path, getcwd
        if isinstance(msg, Message):
            msg = msg.id
        assert is_sha1(msg), 'Message id not a SHA1 hash'
        if adir is None:
            adir = getcwd()
        try:
            response = self.__do_page('download', msg)
        except:
            raise DownloadError
        fn = path.join(adir, '%s.mp3' % msg)
        fo = open(fn, 'wb')
        fo.write(response.read())
        fo.close()
        return fn
    
    def contacts(self):
        """
        Partial data of your Google Account Contacts related to your Voice account.
        For a more comprehensive suite of APIs, check out
        http://code.google.com/apis/contacts/docs/1.0/developers_guide_python.html
        """
        if hasattr(self, '_contacts'):
            return self._contacts
        self._contacts = self.__get_xml_page('contacts')()
        return self._contacts
    contacts = property(contacts)

    # Helper methods
    @staticmethod
    def __do_page(page, data=None, headers={}):
        """
        Loads a page out of the settings and pass it on to urllib Request
        """
        page = page.upper()
        if isinstance(data, dict) or isinstance(data, tuple):
            data = urlencode(data)
        headers.update({'User-Agent': 'PyGoogleVoice/0.5'})
        if log:
            log.debug('%s?%s - %s' % (getattr(settings, page)[22:], data or '', headers))
        if page in ('DOWNLOAD', 'XML_SEARCH'):
            return urlopen(Request(getattr(settings, page) + data, None, headers))
        if data:
            headers.update({'Content-type': 'application/x-www-form-urlencoded;charset=utf-8'})
        if isinstance(data, str):
            data = data.encode("ascii")
        return urlopen(Request(getattr(settings, page), data, headers))

    def __validate_special_page(self, page, data={}, **kwargs):
        """
        Validates a given special page for an 'ok' response
        """
        data.update(kwargs)
        load_and_validate(self.__do_special_page(page, data))

    _Phone__validate_special_page = __validate_special_page
    
    def __do_special_page(self, page, data=None, headers={}):
        """
        Add self.special to request data
        """
        assert self.special, 'You must login before using this page'
        if isinstance(data, tuple):
            data += ('_rnr_se', self.special)
        elif isinstance(data, dict):
            data.update({'_rnr_se': self.special})
        return self.__do_page(page, data, headers)
        
    _Phone__do_special_page = __do_special_page
    
    def __get_xml_page(self, page, data=None, headers={}):
        """
        Return XMLParser instance generated from given page
        """
        return XMLParser(self,
                         page,
                         lambda: self.__do_special_page('XML_%s' % page.upper(),
                                                        data,
                                                        headers).read())
      
    def __messages_post(self, page, *msgs, **kwargs):
        """
        Performs message operations, eg deleting,staring,moving
        """
        data = kwargs.items()
        for msg in msgs:
            if isinstance(msg, Message):
                msg = msg.id
            assert is_sha1(msg), 'Message id not a SHA1 hash'
            data += (('messages', msg),)
        return self.__do_special_page(page, dict(data))
    
    _Message__messages_post = __messages_post