from flask_wtf import FlaskForm
from flask_login import current_user
from wtforms import StringField, PasswordField, BooleanField, SubmitField, SelectMultipleField, SelectField, TextAreaField, IntegerField, FileField, HiddenField, FieldList, FormField
from wtforms.validators import DataRequired, Email, EqualTo, ValidationError, Optional, Length, Regexp, NumberRange, InputRequired
from app.models import User, Role, League
from sqlalchemy import func
import logging

# Get the logger for this module
logger = logging.getLogger(__name__)

# Defining the options outside the class
soccer_positions = [
    ('goalkeeper', 'Goalkeeper'),
    ('defender', 'Defender'),
    ('midfielder', 'Midfielder'),
    ('forward', 'Forward'),
    ('winger', 'Winger'),
    ('striker', 'Striker'),
    ('center_back', 'Center Back'),
    ('full_back', 'Full Back'),
    ('wing_back', 'Wing Back'),
    ('attacking_midfielder', 'Attacking Midfielder'),
    ('defensive_midfielder', 'Defensive Midfielder'),
    ('central_midfielder', 'Central Midfielder'),
    ('no_preference', 'No Preference')
]

goal_frequency_choices = [
    ('0', 'Never'),
    ('1', 'Only if our normal GK is unavailable and there are no other options'),
    ('2', 'I will fill in as much as needed, but expect to play in the field'),
    ('3', 'Half of the time'),
    ('4', 'Every Game')
]

availability_choices = [
    ('1-2', '1-2'),
    ('3-4', '3-4'),
    ('5-6', '5-6'),
    ('7-8', '7-8'),
    ('9-10', '9-10')
]

pronoun_choices = [
    ('he/him', 'He/Him'),
    ('she/her', 'She/Her'),
    ('they/them', 'They/Them'),
    ('other', 'Other')
]

willing_to_referee_choices = [
    ('No', 'No'),
    ("Yes - I'll ref in Classic only", "Yes - I'll ref in Classic only"),
    ("Yes - I'll ref in Premier only", "Yes - I'll ref in Premier only"),
    ("Yes - I'll ref in Premier or Classic", "Yes - I'll ref in Premier or Classic"),
    ("I am interested in receiving ref training only", "I am interested in receiving ref training only")
]

# Combined OnboardingForm
class OnboardingForm(FlaskForm):
    # PlayerProfileForm Fields
    name = StringField('Name', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional()])
    jersey_size = SelectField('Jersey Size', choices=[], validators=[Optional()])
    jersey_number = IntegerField('Jersey Number', validators=[Optional()])
    profile_picture = FileField('Profile Picture', validators=[Optional()])

    pronouns = SelectField('Preferred Pronouns', choices=pronoun_choices, validators=[Optional()])
    expected_weeks_available = SelectField('Expected Availability (Weeks)', choices=availability_choices, validators=[Optional()])
    unavailable_dates = StringField('Unavailable Dates', validators=[Optional()])
    willing_to_referee = SelectField('Interested in Refereeing?', choices=willing_to_referee_choices, validators=[Optional()])

    favorite_position = SelectField('Favorite Position', choices=soccer_positions, validators=[Optional()])
    other_positions = SelectMultipleField('Other Positions Enjoyed', choices=soccer_positions, validators=[Optional()])
    positions_not_to_play = SelectMultipleField('Positions to Avoid', choices=soccer_positions, validators=[Optional()])

    frequency_play_goal = SelectField('Goal Frequency', choices=goal_frequency_choices, validators=[Optional()])
    additional_info = TextAreaField('Additional Information', validators=[Optional()])
    player_notes = TextAreaField('Player Notes', validators=[Optional()])
    team_swap = SelectField('Willing to Switch Teams for a Day if Needed?', choices=[('yes', 'Yes'), ('no', 'No'), ('maybe', 'Maybe')], validators=[Optional()])

    # SettingsForm Fields
    email_notifications = BooleanField('Email Notifications')
    sms_notifications = BooleanField('SMS Notifications')
    discord_notifications = BooleanField('Discord Notifications')
    profile_visibility = SelectField('Profile Visibility', choices=[('everyone', 'Everyone'), ('teammates', 'Teammates'), ('private', 'Private')])

    submit = SubmitField('Submit')

def to_int(value):
    try:
        if value is None or value == '':
            return 0
        return int(value)
    except (TypeError, ValueError):
        raise ValidationError('Not a valid integer value.')

class LoginForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    remember = BooleanField('Remember Me')
    submit = SubmitField('Sign In')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    roles = SelectMultipleField('Roles', validators=[DataRequired()])
    submit = SubmitField('Register')

    def __init__(self, *args, **kwargs):
        super(RegistrationForm, self).__init__(*args, **kwargs)
        self.roles.choices = [(role.name, role.name) for role in Role.query.all()]

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose a different one.')

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('That email is already in use. Please choose a different one.')

class CreateUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired(), EqualTo('confirm_password')])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired()])
    roles = SelectMultipleField('Roles', validators=[DataRequired()])
    league_id = SelectField('League', coerce=int, choices=[], validators=[Optional()])
    is_current_player = BooleanField('Is Current Player', default=False)
    submit = SubmitField('Create User')

    def __init__(self, *args, **kwargs):
        super(CreateUserForm, self).__init__(*args, **kwargs)
        self.roles.choices = [(role.id, role.name) for role in Role.query.all()]
        self.league_id.choices = [(0, 'None')] + [(league.id, league.name) for league in League.query.all()]  # Ensure field is named league_id

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user:
            raise ValidationError('Email is already in use. Please choose a different one.')

class PlayerProfileForm(FlaskForm):
    name = StringField('Name', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    phone = StringField('Phone', validators=[Optional()])
    jersey_size = SelectField('Jersey Size', choices=[], validators=[Optional()])
    jersey_number = IntegerField('Jersey Number', validators=[Optional()])
    profile_picture = FileField('Profile Picture', validators=[Optional()])
    edit_career_stats = HiddenField(default='false')

    pronouns = SelectField('Preferred Pronouns', choices=pronoun_choices, validators=[Optional()])
    expected_weeks_available = SelectField('Expected Availability (Weeks)', choices=availability_choices, validators=[Optional()])
    unavailable_dates = StringField('Unavailable Dates', validators=[Optional()])
    willing_to_referee = SelectField('Interested in Refereeing?', choices=willing_to_referee_choices, validators=[Optional()])

    favorite_position = SelectField('Favorite Position', choices=soccer_positions, validators=[Optional()])
    other_positions = SelectMultipleField('Other Positions Enjoyed', choices=soccer_positions, validators=[Optional()])
    positions_not_to_play = SelectMultipleField('Positions to Avoid', choices=soccer_positions, validators=[Optional()])

    frequency_play_goal = SelectField('Goal Frequency', choices=goal_frequency_choices, validators=[Optional()])
    additional_info = TextAreaField('Additional Information', validators=[Optional()])
    player_notes = TextAreaField('Player Notes', validators=[Optional()])
    team_swap = SelectField('Willing to Switch Teams for a Day if Needed?', choices=[('yes', 'Yes'), ('no', 'No'), ('maybe', 'Maybe')], validators=[Optional()])

    # Admin-only fields
    notes = TextAreaField('Admin Notes', validators=[Optional()])
    is_coach = BooleanField('Coach', validators=[Optional()])

class SeasonStatsForm(FlaskForm):
    season_goals = IntegerField('Season Goals', filters=[to_int], validators=[Optional()])
    season_assists = IntegerField('Season Assists', filters=[to_int], validators=[Optional()])
    season_yellow_cards = IntegerField('Season Yellow Cards', filters=[to_int], validators=[Optional()])
    season_red_cards = IntegerField('Season Red Cards', filters=[to_int], validators=[Optional()])

class CareerStatsForm(FlaskForm):
    career_goals = IntegerField('Career Goals', filters=[to_int], validators=[Optional()])
    career_assists = IntegerField('Career Assists', filters=[to_int], validators=[Optional()])
    career_yellow_cards = IntegerField('Career Yellow Cards', filters=[to_int], validators=[Optional()])
    career_red_cards = IntegerField('Career Red Cards', filters=[to_int], validators=[Optional()])

class UpdateRoleForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    roles = SelectMultipleField('Roles', validators=[DataRequired()])
    submit = SubmitField('Update Roles')

    def __init__(self, *args, **kwargs):
        super(UpdateRoleForm, self).__init__(*args, **kwargs)
        self.roles.choices = [(role.name, role.name) for role in Role.query.all()]

class ForgotPasswordForm(FlaskForm):
    email = StringField('Email', validators=[DataRequired(), Email()])
    submit = SubmitField('Request Password Reset')

class ResetPasswordForm(FlaskForm):
    password = PasswordField('New Password', validators=[DataRequired()])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Reset Password')

class EditUserForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email', validators=[DataRequired(), Email()])
    roles = SelectMultipleField('Roles', coerce=int)  # Remove DataRequired validator
    league_id = SelectField('League', coerce=int, choices=[])
    is_current_player = BooleanField('Active Player')
    submit = SubmitField('Update User')

    def __init__(self, user_id=None, *args, **kwargs):
        super(EditUserForm, self).__init__(*args, **kwargs)
        self.user_id = user_id
        self.roles.choices = [(role.id, role.name) for role in Role.query.all()]
        self.league_id.choices = [(0, 'Select League')] + [(league.id, league.name) for league in League.query.all()]

        if user_id:
            user = User.query.get(user_id)
            if user:
                self.roles.data = [role.id for role in user.roles]
                if user.player:
                    self.league_id.data = user.player.league_id
                    self.is_current_player.data = user.player.is_current_player

    def validate_email(self, email):
        user = User.query.filter_by(email=email.data).first()
        if user and user.id != self.user_id:
            raise ValidationError('Email is already in use. Please choose a different one.')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user and user.id != self.user_id:
            raise ValidationError('Username is already taken. Please choose a different one.')

class NotificationSettingsForm(FlaskForm):
    email_notifications = BooleanField('Email Notifications')
    sms_notifications = BooleanField('SMS Notifications')
    discord_notifications = BooleanField('Discord Notifications')
    profile_visibility = SelectField('Profile Visibility', choices=[('everyone', 'Everyone'), ('teammates', 'Teammates'), ('private', 'Private')])
    submit_notifications = SubmitField('Save Changes')

class PasswordChangeForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired(message="Please enter your current password.")])
    new_password = PasswordField('New Password', validators=[
        DataRequired(message="Please enter a new password."),
        Length(min=8, message="Password must be at least 8 characters long."),
        Regexp(
            '^(?=.*[A-Z])(?=.*\d)(?=.*[@$!%*?&])[A-Za-z\d@$!%*?&]{8,}$',
            message="Password must contain at least one uppercase letter, one number, and one special character."
        )
    ])
    confirm_new_password = PasswordField('Confirm New Password', validators=[
        DataRequired(message="Please confirm your new password."),
        EqualTo('new_password', message='Passwords must match.')
    ])
    submit_password = SubmitField('Update Password')

class Enable2FAForm(FlaskForm):
    totp_token = StringField('2FA Code', validators=[
        DataRequired(message="Please enter the 2FA code."),
        Length(min=6, max=6, message="2FA code must be exactly 6 digits."),
        Regexp('^\d{6}$', message="2FA code must contain only digits.")
    ])
    submit_enable_2fa = SubmitField('Verify')

class Disable2FAForm(FlaskForm):
    submit_disable_2fa = SubmitField('Disable 2FA')

class EmptyForm(FlaskForm):
    pass

class SubmitForm(FlaskForm):
    submit = SubmitField('Submit')

class AnnouncementForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired()])
    content = TextAreaField('Content', validators=[DataRequired()])
    submit = SubmitField('Save')

class TwoFactorForm(FlaskForm):
    token = StringField('2FA Token', validators=[DataRequired()])
    submit = SubmitField('Verify')

class Verify2FAForm(FlaskForm):
    totp_token = StringField('2FA Token', validators=[DataRequired()])
    submit = SubmitField('Verify')

class PlayerEventForm(FlaskForm):
    player_id = SelectField('Player', coerce=int, validators=[DataRequired()])
    minute = IntegerField('Minute', validators=[Optional(), NumberRange(min=1, max=120)])

class ReportMatchForm(FlaskForm):
    home_team_score = IntegerField('Home Team Score', validators=[InputRequired(message="This field is required"), NumberRange(min=0)])
    away_team_score = IntegerField('Away Team Score', validators=[InputRequired(message="This field is required"), NumberRange(min=0)])
    
    goal_scorers = FieldList(FormField(PlayerEventForm), min_entries=0, max_entries=10)
    assist_providers = FieldList(FormField(PlayerEventForm), min_entries=0, max_entries=10)
    yellow_cards = FieldList(FormField(PlayerEventForm), min_entries=0, max_entries=10)
    red_cards = FieldList(FormField(PlayerEventForm), min_entries=0, max_entries=10)

    notes = TextAreaField('Match Notes')

class CreatePlayerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    email = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    jersey_size = SelectField('Jersey Size', validators=[DataRequired()], choices=[])  # Choices will be set in the view
    league_id = SelectField('League', validators=[DataRequired()], choices=[])  # Choices will be set in the view
    csrf_token = HiddenField()  # CSRF token

    def validate_email(self, field):
        email = field.data.lower()
        if User.query.filter(func.lower(User.email) == email).first():
            raise ValidationError('Email is already registered.')

class EditPlayerForm(FlaskForm):
    name = StringField('Name', validators=[DataRequired(), Length(max=100)])
    phone = StringField('Phone Number', validators=[DataRequired(), Length(max=20)])
    jersey_size = SelectField('Jersey Size', validators=[DataRequired()], choices=[])
    league_id = SelectField('League', validators=[DataRequired()], choices=[])
    submit = SubmitField('Update Player')