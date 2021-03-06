import os
import logging
import datetime

import sys
import re
import traceback
import gae_bingo.identity

from google.appengine.api import users
from google.appengine.runtime.apiproxy_errors import CapabilityDisabledError

import webapp2
import shared_jinja

from custom_exceptions import MissingVideoException, MissingExerciseException, SmartHistoryLoadException, PageNotFoundException, QuietException
from app import App
import cookie_util

from api.jsonify import jsonify
from gae_bingo.gae_bingo import ab_test

class RequestInputHandler(object):

    def request_string(self, key, default=''):
        return self.request.get(key, default_value=default)
    
    def request_continue_url(self, key="continue", default="/"):
        """ Gets the request string representing a continue URL for the current
        request.
        
        This will safely filter out continue URL's that are not-served by
        us so that users can't be tricked into going to a malicious site post
        login or some other flow that goes through KA.
        """
        val = self.request_string(key, default)
        if val and not App.is_dev_server and not util.is_khanacademy_url(val):
            logging.warn("Invalid continue URI [%s]. Ignoring." % val)
            if val != default and util.is_khanacademy_url(default):
                # Make a last ditch effort to try the default, in case the
                # explicit continue URI was the bad one
                return default
            return "/"

        return val

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
            return datetime.datetime.strptime(s_date, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            if default is not None:
                return default
            else:
                raise # No value available and no default supplied, raise error

    # TODO(benkomalo): kill this, or make it private and
    # consolidate it with the other request user data methods by
    # various email keys
    def request_user_data(self, key):
        email = self.request_string(key)
        return user_models.UserData.get_possibly_current_user(email)

    def request_visible_student_user_data(self):
        """Return the UserData for the given request.
        
        This looks for an identifying parameter
        (see request_student_user_data) and attempts to return that user
        if the current actor for the request has access to view that
        user's information (will return None if the actor does not
        have sufficient permissions)

        If no identifying parameter is specified, returns the current user.
        """
        override_user_data = self.request_student_user_data()
        if not override_user_data:
            # TODO(benkomalo): maybe this shouldn't fallback to current user?
            # It seems like a weird API to accept an explicit user identifier
            # but then fallback to the current user if that identifier doesn't
            # resolve. It should give an error instead.
            return user_models.UserData.current()
        return user_models.UserData.get_visible_user(override_user_data)

    def request_student_user_data(self):
        """Return the specified UserData for the given request.
        
        This looks for an identifying parameter, looking first for userID,
        then username, then email, from the request parameters and returns
        the user that matches, if any.
        """
        current = user_models.UserData.current()
        user_id = self.request_string("userID")
        if user_id:
            if current and current.user_id == user_id:
                return current
            return user_models.UserData.get_from_user_id(user_id)

        username = self.request_string("username")
        if username:
            if current and user_models.UniqueUsername.matches(
                    current.username, username):
                return current
            return user_models.UserData.get_from_username(username)

        email = self._request_student_email()
        if email:
            if current and current.email == email:
                return current
            return user_models.UserData.get_from_user_input_email(email)

        return None

    def _request_student_email(self):
        """Retrieve email parameter from the request.

        This abstracts away some history behind the name changes for the email
        parameter and is robust to handling "student_email" and "email"
        parameter names.
        """
        email = self.request_string("student_email")
        if email:
            logging.warning("API called with legacy student_email parameter")
        email = self.request_string("email", email)
        return email

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

class RequestHandler(webapp2.RequestHandler, RequestInputHandler):

    class __metaclass__(type):
        """Enforce that subclasses of RequestHandler decorate get()/post()/etc.
        This metaclass enforces that whenever we create a
        RequestHandler or subclass thereof, that the class we're
        creating has a decorator on its get(), post(), and other
        http-verb methods that specify the access needed to get or
        post (admin, moderator, etc).

        It does this through a two-step process.  In step 1, we make
        all the access-control decorators set a function-global
        variable in the method they're decorating.  (This is done in
        the decorator definitions in user_util.py.)  In step 2, here,
        we check that that variable is defined.  We can do this
        because metaclass, when creating a new class, has access to
        the functions (methods) that the class implements.

        Note that this check happens at import-time, so we don't have
        to worry about this assertion triggering surprisingly in
        production.
        """
        def __new__(mcls, name, bases, attrs):
            for fn in ("get", "post", "head", "put"):
                if fn in attrs:
                    # TODO(csilvers): remove the requirement that the
                    # access control decorator go first.  To do that,
                    # we'll have to store state somewhere other than
                    # in func_dict (which later decorators overwrite).
                    assert '_access_control' in attrs[fn].func_dict, \
                           ('FATAL ERROR: '
                            'Need to put an access control decorator '
                            '(from user_util) on %s.%s. '
                            '(It must be the topmost decorator for the method.)'
                            % (name, fn))
            return type.__new__(mcls, name, bases, attrs)

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
        
        title = "Oops. We made a mistake."
        message_html = "We ran into a problem. It's our fault, and we're working on it."
        sub_message_html = "This has been reported to us, and we'll be looking for a fix. If the problem continues, feel free to <a href='/reportissue?type=Defect'>send us a report directly</a>."

        if type(e) is CapabilityDisabledError:

            # App Engine maintenance period
            title = "Shhh. We're studying."
            message_html = "We're temporarily down for maintenance, and we expect this to end shortly. In the meantime, you can watch all of our videos at the <a href='http://www.youtube.com/user/khanacademy'>Khan Academy YouTube channel</a>."
            sub_message_html = "We're really sorry for the inconvenience, and we're working to restore access as soon as possible."

        elif type(e) is MissingExerciseException:

            title = "This exercise isn't here right now."
            message_html = "Either this exercise doesn't exist or it's temporarily hiding. You should <a href='/exercisedashboard'>head back to our other exercises</a>."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        elif type(e) is MissingVideoException:

            # We don't log missing videos as errors because they're so common due to malformed URLs or renamed videos.
            # Ask users to report any significant problems, and log as info in case we need to research.
            title = "This video is no longer around."
            message_html = "You're looking for a video that either never existed or wandered away. <a href='/'>Head to our video library</a> to find it."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        elif type(e) is SmartHistoryLoadException:
            # 404s are very common with Smarthistory as bots have gotten hold of bad urls, silencing these reports and log as info instead
            title = "This page of the Smarthistory section of Khan Academy does not exist"
            message_html = "Go to <a href='/'>our Smarthistory homepage</a> to find more art history content."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        elif type(e) is PageNotFoundException:

            title = "Sorry, we can't find what you're looking for."
            message_html = "This page doesn't seem to be around. <a href='/'>Head to our homepage</a> instead."
            sub_message_html = "If this problem continues and you think something is wrong, please <a href='/reportissue?type=Defect'>let us know by sending a report</a>."

        if isinstance(e, QuietException):
            logging.info(e)
        else:
            self.error(500)
            logging.exception(e)

        # Show a nice stack trace on development machines, but not in production
        if App.is_dev_server or users.is_current_user_admin():
            try:
                import google

                exc_type, exc_value, exc_traceback = sys.exc_info()

                # Grab module and convert "__main__" to just "main"
                class_name = '%s.%s' % (re.sub(r'^__|__$', '', self.__class__.__module__), type(self).__name__)

                http_method = self.request.method
                title = '%s in %s.%s' % ((exc_value.exc_info[0] if hasattr(exc_value, 'exc_info') else exc_type).__name__, class_name, http_method.lower())

                message = str(exc_value.exc_info[1]) if hasattr(exc_value, 'exc_info') else str(exc_value)

                sdk_root = os.path.normpath(os.path.join(os.path.dirname(google.__file__), '..'))
                sdk_version = os.environ['SDK_VERSION'] if os.environ.has_key('SDK_VERSION') else os.environ['SERVER_SOFTWARE'].split('/')[-1]
                app_root = App.root
                r_sdk_root = re.compile(r'^%s/' % re.escape(sdk_root))
                r_app_root = re.compile(r'^%s/' % re.escape(app_root))

                (template_filename, template_line, extracted_source) = (None, None, None)
                if hasattr(exc_value, 'source'):
                    origin, (start, end) = exc_value.source
                    template_filename = str(origin)

                    f = open(template_filename)
                    template_contents = f.read()
                    f.close()

                    template_lines = template_contents.split('\n')
                    template_line = 1 + template_contents[:start].count('\n')
                    template_end_line = 1 + template_contents[:end].count('\n')

                    ctx_start = max(1, template_line - 3)
                    ctx_end = min(len(template_lines), template_end_line + 3)

                    extracted_source = '\n'.join('%s: %s' % (num, template_lines[num - 1]) for num in range(ctx_start, ctx_end + 1))

                def format_frame(frame):
                    filename, line, function, text = frame
                    filename = r_sdk_root.sub('google_appengine (%s) ' % sdk_version, filename)
                    filename = r_app_root.sub('', filename)
                    return "%s:%s:in `%s'" % (filename, line, function)

                extracted = traceback.extract_tb(exc_traceback)
                if hasattr(exc_value, 'exc_info'):
                    extracted += traceback.extract_tb(exc_value.exc_info[2])

                application_frames = reversed([frame for frame in extracted if r_app_root.match(frame[0])])
                framework_frames = reversed([frame for frame in extracted if not r_app_root.match(frame[0])])
                full_frames = reversed([frame for frame in extracted])

                application_trace = '\n'.join(format_frame(frame) for frame in application_frames)
                framework_trace = '\n'.join(format_frame(frame) for frame in framework_frames)
                full_trace = '\n'.join(format_frame(frame) for frame in full_frames)

                param_keys = self.request.arguments()
                params = ',\n    '.join('%s: %s' % (repr(k.encode('utf8')), repr(self.request.get(k).encode('utf8'))) for k in param_keys)
                params_dump = '{\n    %s\n}' % params if len(param_keys) else '{}'

                environ = self.request.environ
                env_dump = '\n'.join('%s: %s' % (k, environ[k]) for k in sorted(environ))

                self.response.clear()
                self.render_jinja2_template('viewtraceback.html', { "title": title, "message": message, "template_filename": template_filename, "template_line": template_line, "extracted_source": extracted_source, "app_root": app_root, "application_trace": application_trace, "framework_trace": framework_trace, "full_trace": full_trace, "params_dump": params_dump, "env_dump": env_dump })
            except:
                # We messed something up showing the backtrace nicely; just show it normally
                pass
        else:
            self.response.clear()
            self.render_jinja2_template('viewerror.html', { "title": title, "message_html": message_html, "sub_message_html": sub_message_html })

    @classmethod
    def exceptions_to_http(klass, status):
        def decorator(fn):
            def wrapper(self, *args, **kwargs):
                try:
                    fn(self, *args, **kwargs);
                except Exception, e:
                    self.response.clear()
                    self.response.set_status(status)
            return wrapper
        return decorator

    def user_agent(self):
        return str(self.request.headers.get('User-Agent', ""))

    def is_mobile_capable(self):
        user_agent_lower = self.user_agent().lower()
        return user_agent_lower.find("ipod") > -1 or \
                user_agent_lower.find("ipad") > -1 or \
                user_agent_lower.find("iphone") > -1 or \
                user_agent_lower.find("webos") > -1 or \
                user_agent_lower.find("android") > -1

    def is_older_ie(self):
        user_agent_lower = self.user_agent().lower()
        return user_agent_lower.find("msie 7.") > -1 or \
                user_agent_lower.find("msie 6.") > -1

    def is_webos(self):
        user_agent_lower = self.user_agent().lower()
        return user_agent_lower.find("webos") > -1 or \
                user_agent_lower.find("hp-tablet") > -1

    def is_ipad(self):
        user_agent_lower = self.user_agent().lower()
        return user_agent_lower.find("ipad") > -1

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

        # We manually add the header here so we can support httponly cookies in Python 2.5,
        # which self.response.set_cookie does not.
        header_value = cookie_util.set_cookie_value(key, value, max_age, path, domain, secure, httponly, version, comment)
        self.response.headerlist.append(('Set-Cookie', header_value))

    def delete_cookie_including_dot_domain(self, key, path='/', domain=None):

        self.delete_cookie(key, path, domain)

        if domain is None:
            domain = os.environ["SERVER_NAME"]

        self.delete_cookie(key, path, "." + domain)

    def delete_cookie(self, key, path='/', domain=None):
        self.set_cookie(key, '', path=path, domain=domain, max_age=0)

    def add_global_template_values(self, template_values):
        template_values['App'] = App
        template_values['None'] = None

        if not template_values.has_key('user_data'):
            user_data = user_models.UserData.current()
            template_values['user_data'] = user_data

        user_data = template_values['user_data']

        template_values['username'] = user_data.nickname if user_data else ""
        template_values['viewer_profile_root'] = user_data.profile_root if user_data else "/profile/nouser/"
        template_values['points'] = user_data.points if user_data else 0
        template_values['logged_in'] = not user_data.is_phantom if user_data else False
        template_values['http_host'] = os.environ["HTTP_HOST"]

        # Always insert a post-login request before our continue url
        template_values['continue'] = util.create_post_login_url(template_values.get('continue') or self.request.uri)
        template_values['login_url'] = ('%s&direct=1' % util.create_login_url(template_values['continue']))
        template_values['logout_url'] = util.create_logout_url(self.request.uri)

        template_values['is_mobile'] = False
        template_values['is_mobile_capable'] = False
        template_values['is_ipad'] = False

        if self.is_mobile_capable():
            template_values['is_mobile_capable'] = True
            template_values['is_ipad'] = self.is_ipad()

            if 'is_mobile_allowed' in template_values and template_values['is_mobile_allowed']:
                template_values['is_mobile'] = self.is_mobile()

        # overridable hide_analytics querystring that defaults to true in dev
        # mode but false for prod.
        hide_analytics = self.request_bool("hide_analytics", App.is_dev_server)
        template_values['hide_analytics'] = hide_analytics

        # client-side error logging
        template_values['include_errorception'] = gandalf('errorception')

        # Analytics
        template_values['mixpanel_enabled'] = gandalf('mixpanel_enabled')

        if False: # Enable for testing only
            template_values['mixpanel_test'] = "70acc4fce4511b89477ac005639cfee1"
            template_values['mixpanel_enabled'] = True
            template_values['hide_analytics'] = False

        if template_values['mixpanel_enabled']:
            template_values['mixpanel_id'] = gae_bingo.identity.identity()

        if not template_values['hide_analytics']:
            superprops_list = user_models.UserData.get_analytics_properties(user_data)

            # Create a superprops dict for MixPanel with a version number
            # Bump the version number if changes are made to the client-side analytics
            # code and we want to be able to filter by version.
            template_values['mixpanel_superprops'] = dict(superprops_list)

            # Copy over first 4 per-user properties for GA (5th is reserved for Bingo)
            template_values['ga_custom_vars'] = superprops_list[0:4]

        if user_data:
            user_goals = goals.models.GoalList.get_current_goals(user_data)
            goals_data = [g.get_visible_data() for g in user_goals]
            if goals_data:
                template_values['global_goals'] = jsonify(goals_data)

        # Disable topic browser in the header on mobile devices
        template_values['watch_topic_browser_enabled'] = not self.is_mobile_capable()

        # Begin topic pages A/B test
        if template_values['mixpanel_enabled']:
            show_topic_pages = ab_test("Show topic pages", ["show", "hide"], ["topic_pages_view_page", "topic_pages_started_video", "topic_pages_completed_video"])
            analytics_bingo = {"name": "Bingo: Topic pages", "value": show_topic_pages}
            template_values['analytics_bingo'] = analytics_bingo
        else:
            show_topic_pages = "hide"
        template_values['show_topic_pages'] = (show_topic_pages == "show")
        # End topic pages A/B test

        return template_values

    def render_jinja2_template(self, template_name, template_values):
        self.add_global_template_values(template_values)
        self.response.write(self.render_jinja2_template_to_string(template_name, template_values))

    def render_jinja2_template_to_string(self, template_name, template_values):
        return shared_jinja.template_to_string(template_name, template_values)

    def render_json(self, obj, camel_cased=False):
        json_string = jsonify(obj, camel_cased=camel_cased)
        self.response.content_type = "application/json"
        self.response.out.write(json_string)

    def render_jsonp(self, obj, camel_cased=False):
        if isinstance(obj, basestring):
            json_string = obj
        else:
            json_string = jsonify(obj, camel_cased=camel_cased)
        callback = self.request_string("callback")
        if callback:
            self.response.out.write("%s(%s)" % (callback, json_string))
        else:
            self.response.out.write(json_string)

import goals.models
import user_models
import util
from gandalf import gandalf
