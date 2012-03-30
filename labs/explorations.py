from api.auth.xsrf import ensure_xsrf_cookie
from custom_exceptions import MissingExerciseException
import request_handler

EXPLORATIONS = [
    # Crypto
    'frequency-fingerprint',
    'frequency-stability'
]

class RequestHandler(request_handler.RequestHandler):
    @ensure_xsrf_cookie
    def get(self, exploration=None):
        if not exploration:
            self.render_jinja2_template('labs/explorations/index.html', {})
        elif exploration in EXPLORATIONS:
            self.render_jinja2_template('labs/explorations/%s.html' % exploration, {})
        else:
            raise MissingExerciseException('Missing exploration %s' % exploration)
