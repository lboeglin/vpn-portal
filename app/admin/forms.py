from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, Optional, Regexp


class CreateUserPeerForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(3, 80, message="Must be 3–80 characters."),
            Regexp(
                r"^[\w\-]+$",
                message="Letters, digits, underscores, and hyphens only.",
            ),
        ],
    )
    password = PasswordField(
        "Password",
        validators=[
            DataRequired(),
            Length(8, message="Must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            DataRequired(),
            EqualTo("password", message="Passwords must match."),
        ],
    )
    peer_name = StringField(
        "Peer Name",
        description="A label for this VPN config, e.g. 'Laptop' or 'Phone'.",
        validators=[
            DataRequired(),
            Length(1, 80, message="Must be 1–80 characters."),
        ],
    )
    submit = SubmitField("Create User & Peer")


class EditUserForm(FlaskForm):
    username = StringField(
        "Username",
        validators=[
            DataRequired(),
            Length(3, 80, message="Must be 3–80 characters."),
            Regexp(
                r"^[\w\-]+$",
                message="Letters, digits, underscores, and hyphens only.",
            ),
        ],
    )
    password = PasswordField(
        "New Password",
        description="Leave blank to keep the current password.",
        validators=[
            Optional(),
            Length(8, message="Must be at least 8 characters."),
        ],
    )
    confirm_password = PasswordField(
        "Confirm New Password",
        validators=[
            EqualTo("password", message="Passwords must match."),
        ],
    )
    peer_name = StringField(
        "Peer Name",
        validators=[
            DataRequired(),
            Length(1, 80, message="Must be 1–80 characters."),
        ],
    )
    submit = SubmitField("Save Changes")
