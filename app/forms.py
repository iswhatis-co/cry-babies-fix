from flask_wtf import FlaskForm
from wtforms import StringField, BooleanField
from wtforms.validators import DataRequired

class CreatePlaylistForm(FlaskForm):
    user_name = StringField('Name', validators=[DataRequired()])
    mailing_list = BooleanField('Mailing List', default=False)
    spotify_subscribe = BooleanField('Spotify Subscribe', default=False)
