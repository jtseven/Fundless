from flask_login import login_user, LoginManager, UserMixin, logout_user, current_user, login_required
import secrets
from os import environ as env
from dotenv import load_dotenv, find_dotenv
from functools import wraps
from flask import session, redirect, Flask, render_template, url_for, request
from authlib.integrations.flask_client import OAuth
from six.moves.urllib.parse import urlencode

from config import DashboardConfig, LoginProviderEnum, SecretsStore
from utils import Constants


class User(UserMixin):
    def __init__(self, username):
        self.id = username


class LoginProvider:
    def __init__(self, config: DashboardConfig, server: Flask, secrets_store: SecretsStore):
        self.secret_key = secrets.token_hex(24)
        self.provider = config.login_provider
        self.secrets_store = secrets_store

        if self.provider == LoginProviderEnum.custom:
            # config flask login
            server.config.update(SECRET_KEY=self.secret_key)

            # Login manager object will be used to login / logout users
            login_manager = LoginManager()
            login_manager.init_app(server)
            login_manager.login_view = '/login'

            @login_manager.user_loader
            def load_user(username):
                """
                    This function loads the user by user id. Typically this looks up the user from a user database.
                    We won't be registering or looking up users in this example, since we'll just login using LDAP server.
                    So we'll simply return a User object with the passed in username.
                """
                return User(username)

        elif self.provider == LoginProviderEnum.auth0:
            # Constants
            env_file = find_dotenv()
            if env_file:
                load_dotenv(env_file)

            self.AUTH0_CALLBACK_URL = env.get(Constants.AUTH0_CALLBACK_URL)
            self.AUTH0_CLIENT_ID = env.get(Constants.AUTH0_CLIENT_ID)
            self.AUTH0_CLIENT_SECRET = env.get(Constants.AUTH0_CLIENT_SECRET)
            self.AUTH0_DOMAIN = env.get(Constants.AUTH0_DOMAIN)
            self.AUTH0_BASE_URL = 'https://' + self.AUTH0_DOMAIN
            self.AUTH0_AUDIENCE = env.get(Constants.AUTH0_AUDIENCE)

            # auth0 setup
            oauth = OAuth(server)
            self.auth0 = oauth.register(
                'auth0',
                client_id=self.AUTH0_CLIENT_ID,
                client_secret=self.AUTH0_CLIENT_SECRET,
                api_base_url=self.AUTH0_BASE_URL,
                access_token_url=self.AUTH0_BASE_URL + '/oauth/token',
                authorize_url=self.AUTH0_BASE_URL + '/authorize',
                client_kwargs={
                    'scope': 'openid profile email',
                },
            )

    # def login(self, username: str = None, password: str = None):
    #     if self.provider == LoginProviderEnum.custom:
    #         if username is not None:
    #             username = username.lower().strip()
    #         if username == self.secrets_store.dashboard_user and password == self.secrets_store.dashboard_password:
    #             user = User(username)
    #             login_user(user)
    #             return '/dashboard'
    #         else:
    #             return '/login'
    #     elif self.provider == LoginProviderEnum.auth0:
    #         pass  # TODO

    def logout(self):
        if self.provider == LoginProviderEnum.auth0:
            # Clear session stored data
            session.clear()
            # Redirect user to logout endpoint
            params = {'returnTo': url_for('home', _external=True), 'client_id': self.AUTH0_CLIENT_ID}
            return redirect(self.auth0.api_base_url + '/v2/logout?' + urlencode(params))
        elif self.provider == LoginProviderEnum.custom:
            if current_user.is_authenticated:
                logout_user()
                return redirect('/home')
            else:
                return redirect('/login')

    def login_page(self):
        if self.provider == LoginProviderEnum.auth0:
            return self.auth0.authorize_redirect(redirect_uri=self.AUTH0_CALLBACK_URL, audience=self.AUTH0_AUDIENCE)
        elif self.provider == LoginProviderEnum.custom:
            print("using custom login provider")
            email = request.form.get('email')
            password = request.form.get('password')
            print(request)
            print(email)
            print(password)

            if email == self.secrets_store.dashboard_user and password == self.secrets_store.dashboard_password:
                user = User(email)
                login_user(user, remember=True)
                return redirect('/app')
            else:
                return render_template('login.html')

    def is_authenticated(self):
        if self.provider == LoginProviderEnum.custom:
            if hasattr(current_user, 'is_authenticated') and current_user.is_authenticated:
                return True
            else:
                return False
        elif self.provider == LoginProviderEnum.auth0:
            if Constants.PROFILE_KEY in session:
                return True
            else:
                return False
        else:
            raise ValueError("Unknown login provider selected in config!")

    def auth0_callback(self):
        if self.provider != LoginProviderEnum.auth0:
            return redirect('/login')
            # raise ValueError('The auth0 callback method should only be executed if auth0 is used as login provider!')
        else:
            self.auth0.authorize_access_token()
            resp = self.auth0.get('userinfo')
            userinfo = resp.json()

            session[Constants.JWT_PAYLOAD] = userinfo
            session[Constants.PROFILE_KEY] = {
                'user_id': userinfo['sub'],
                'name': userinfo['name'],
                'picture': userinfo['picture']
            }
            # session['user_config'] = TradingBotConfig.from_dict(
            #     userinfo['http://fundless.jtseven.de/user_metadata']['trading_bot']).json()

            return redirect('/app')

    # Function decorator for website callbacks that require an authenticated user
    def requires_auth(self, f):
        if self.provider == LoginProviderEnum.auth0:
            @wraps(f)
            def decorated(*args, **kwargs):
                if Constants.PROFILE_KEY not in session:
                    # Redirect to Login page here
                    return redirect('/login')
                return f(*args, **kwargs)
            return decorated
        elif self.provider == LoginProviderEnum.custom:
            return login_required(f)
        else:
            raise ValueError('No valid login provider set in dashboard config!')
