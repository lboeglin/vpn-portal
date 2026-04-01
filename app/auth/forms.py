from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, EqualTo, Length


class LoginForm(FlaskForm):
    username = StringField(
        "Username", validators=[DataRequired(), Length(min=1, max=80)]
    )
    password = PasswordField("Password", validators=[DataRequired()])
    submit = SubmitField("Login")


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField(
        "New Password", validators=[DataRequired(), Length(min=8)]
    )
    confirm_new_password = PasswordField(
        "Confirm New Password",
        validators=[
            DataRequired(),
            EqualTo("new_password", message="Passwords must match."),
        ],
    )
    submit = SubmitField("Change Password")
