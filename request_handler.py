import os
import logging
import datetime
import urllib

from django.utils import simplejson
from google.appengine.api import users
from google.appengine.ext import webapp
from google.appengine.ext.webapp import template
from google.appengine.runtime.apiproxy_errors import CapabilityDisabledError

from custom_exceptions import MissingVideoException, MissingExerciseException
import util
from app import App
from render import render_block_to_string
from nicknames import get_nickname_for
import cookie_util

class RequestInputHandler(object):

    def request_string(self, key, default = ''):
        return self.request.get(key, default_value=default)

    def request_int(self, key, default = None):
        try:
            return int(self.request_string(key))
        except ValueError:
            if default is not None:
                return default
            else:
                raise # No value available and no default supplied, raise error

    def request_date(self, key, format_string, default = None):
        try:
            return datetime.datetime.strptime(self.request_string(key), format_string)
        except ValueError:
            if default is not None:
                return default
            else:
                raise # No value available and no default supplied, raise error

    def request_date_iso(self, key, default = None):
        s_date = self.request_string(key)

        # Pull out milliseconds b/c Python 2.5 doesn't play nicely w/ milliseconds in date format strings
        if "." in s_date:
            s_date = s_date[:s_date.find(".")]

        # Try to parse date in our approved ISO 8601 format
        try:
            return datetime.datetime.strptime(s_date, "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            if default is not None:
                return default
            else:
                raise # No value available and no default supplied, raise error

    def request_user_data(self, key):
        return UserData.get_from_user_input(self.request_string(key))

    def request_float(self, key, default = None):
        try:        
            return float(self.request_string(key))
        except ValueError:
            if default is not None:
                return default
            else:
                raise # No value available and no default supplied, raise error

    def request_bool(self, key, default = None):
        if default is None:
            return self.request_int(key) == 1
        else:
            return self.request_int(key, 1 if default else 0) == 1

class RequestHandler(webapp.RequestHandler, RequestInputHandler):

    def is_ajax_request(self):
        # jQuery sets X-Requested-With header for this detection.
        if self.request.headers.has_key("x-requested-with"):
            s_requested_with = self.request.headers["x-requested-with"]
            if s_requested_with and s_requested_with.lower() == "xmlhttprequest":
                return True
        return self.request_bool("is_ajax_override", default=False)

    def request_url_with_additional_query_params(self, params):
        url = self.request.url
        if url.find("?") > -1:
            url += "&"
        else:
            url += "?"
        return url + params

    def handle_exception(self, e, *args):

        silence_report = False

        title = "Oops. We broke our streak."
        message_html = "We ran into a problem. It's our fault, and we're working on it."
        sub_message_html = "This has been reported to us, and we'll be looking for a fix. If the problem continues, feel free to <a href='/reportissue?type=Defect'>send us a report directly</a>."

        if type(e) is CapabilityDisabledError:

            # App Engine maintenance period
            message_html = "We're temporarily down for maintenance. Try again in about an hour. We're sorry for the inconvenience."

        elif type(e) is MissingExerciseException:

            title = "This exercise isn't here right now."
            message_html = "Either this exercise doesn't exist or it's temporarily hiding. You should <a href='/exercisedashboard'>head back to our other exercises</a>."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        elif type(e) is MissingVideoException:

            # We don't log missing videos as errors because they're so common due to malformed URLs or renamed videos.
            # Ask users to report any significant problems, and log as info in case we need to research.
            silence_report = True
            logging.info(e)
            title = "This video is no longer around."
            message_html = "You're looking for a video that either never existed or wandered away. <a href='/'>Head to our video library</a> to find it."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        if not silence_report:
            webapp.RequestHandler.handle_exception(self, e, args)

        # Never show stack traces on production machines
        if not App.is_dev_server:
            self.response.clear()

        self.render_template('viewerror.html', { "title": title, "message_html": message_html, "sub_message_html": sub_message_html })

    def user_agent(self):
        return str(self.request.headers['User-Agent'])

    def is_mobile_capable(self):
        user_agent_lower = self.user_agent().lower()
        return user_agent_lower.find("ipod") > -1 or \
                user_agent_lower.find("ipad") > -1 or \
                user_agent_lower.find("iphone") > -1 or \
                user_agent_lower.find("webos") > -1 or \
                user_agent_lower.find("android") > -1

    def is_mobile(self):
        if self.is_mobile_capable():
            return not self.has_mobile_full_site_cookie()
        return False

    def has_mobile_full_site_cookie(self):
        return self.get_cookie_value("mobile_full_site") == "1"

    def set_mobile_full_site_cookie(self, is_mobile):
        self.set_cookie("mobile_full_site", "1" if is_mobile else "0")

    @staticmethod
    def get_cookie_value(key):
        return cookie_util.get_cookie_value(key)

    # Cookie handling from http://appengine-cookbook.appspot.com/recipe/a-simple-cookie-class/
    def set_cookie(self, key, value='', max_age=None,
                   path='/', domain=None, secure=None, httponly=False,
                   version=None, comment=None):
        header_value = cookie_util.set_cookie_value(key, value, max_age, path, domain, secure, httponly, version, comment)
        self.response.headers._headers.append(('Set-Cookie', header_value))

    def delete_cookie(self, key, path='/', domain=None):
        self.set_cookie(key, '', path=path, domain=domain, max_age=0)

    def add_global_template_values(self, template_values):
        template_values['App'] = App
        template_values['None'] = None

        if not template_values.has_key('user_data'):
            user_data = UserData.current()
            template_values['user_data'] = user_data

        user_data = template_values['user_data']

        template_values['username'] = get_nickname_for(user_data.display_user)
        template_values['points'] = user_data.points

        # Always insert a post-login request before our continue url
        template_values['continue'] = util.create_post_login_url(template_values.get('continue') or self.request.uri)
        template_values['login_url'] = ('%s&direct=1' % util.create_login_url(template_values['continue']))
        template_values['logout_url'] = util.create_logout_url(self.request.uri)

        template_values['is_mobile'] = False
        template_values['is_mobile_capable'] = False

        if self.is_mobile_capable():
            template_values['is_mobile_capable'] = True
            if 'is_mobile_allowed' in template_values and template_values['is_mobile_allowed']:
                template_values['is_mobile'] = self.is_mobile()

        return template_values

    def render_template(self, template_name, template_values):
        self.add_global_template_values(template_values)
        self.render_template_simple(template_name, template_values)

    def render_template_simple(self, template_name, template_values):
        self.response.out.write(self.render_template_to_string(template_name, template_values))

    @staticmethod
    def render_template_to_string(template_name, template_values):
        path = os.path.join(os.path.dirname(__file__), template_name)
        return template.render(path, template_values)
 
    @staticmethod
    def render_template_block_to_string(template_name, block, context):
        path = os.path.join(os.path.dirname(__file__), template_name)
        return render_block_to_string(path, block, context).strip()

    def render_json(self, obj):
        json = simplejson.dumps(obj, ensure_ascii=False)
        self.response.out.write(json)

    def render_jsonp(self, obj):
        json = obj if type(obj) == str else simplejson.dumps(obj, ensure_ascii=False, indent=4)
        callback = self.request_string("callback")
        if callback:
            self.response.out.write("%s(%s)" % (callback, json))
        else:
            self.response.out.write(json)

from models import UserData
