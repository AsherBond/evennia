"""
In-Game Reporting System

This contrib provides an in-game reporting system, with player-facing commands and a staff
management interface.

# Installation

To install, just add the provided cmdset to your default AccountCmdSet:

    # in commands/default_cmdset.py

    from evennia.contrib.base_systems.ingame_reports import ReportsCmdSet

    class AccountCmdSet(default_cmds.AccountCmdSet):
        # ...

        def at_cmdset_creation(self):
            # ...
            self.add(ReportsCmdSet)

# Features

The contrib provides three commands by default and their associated report types: `CmdBug`, `CmdIdea`,
and `CmdReport` (which is for reporting other players).
            
The `ReportCmdBase` class holds most of the functionality for creating new reports, providing a
convenient parent class for adding your own categories of reports.

The contrib can be further configured through two settings, `INGAME_REPORT_TYPES` and `INGAME_REPORT_STATUS_TAGS`

"""

from django.conf import settings

from evennia import CmdSet
from evennia.utils import create, evmenu, logger, search
from evennia.utils.utils import class_from_module, datetime_format, is_iter, iter_to_str
from evennia.commands.default.muxcommand import MuxCommand
from evennia.comms.models import Msg

from . import menu

_DEFAULT_COMMAND_CLASS = class_from_module(settings.COMMAND_DEFAULT_CLASS)

# the default report types
_REPORT_TYPES = ("bugs", "ideas", "players")
if hasattr(settings, "INGAME_REPORT_TYPES"):
    if is_iter(settings.INGAME_REPORT_TYPES):
        _REPORT_TYPES = settings.INGAME_REPORT_TYPES
    else:
        logger.log_warn(
            "The 'INGAME_REPORT_TYPES' setting must be an iterable of strings; falling back to defaults."
        )


def _get_report_hub(report_type):
    """
    A helper function to retrieve the global script which acts as the hub for a given report type.

    Args:
        report_type (str):  The category of reports to retrieve the script for.

    Returns:
        Script or None:  The global script, or None if it couldn't be retrieved or created

    Note: If no matching valid script exists, this function will attempt to create it.
    """
    hub_key = f"{report_type}_reports"
    # NOTE: due to a regression in GLOBAL_SCRIPTS, we use search_script instead of the container
    if not (hub := search.search_script(hub_key)):
        hub = create.create_script(key=hub_key)
    return hub or None


class CmdManageReports(_DEFAULT_COMMAND_CLASS):
    """
    manage the various reports

    Usage:
        manage [report type]

    Available report types:
        bugs
        ideas
        players

    Initializes a menu for reviewing and changing the status of current reports.
    """

    key = "manage reports"
    aliases = tuple(f"manage {report_type}" for report_type in _REPORT_TYPES)
    locks = "cmd:pperm(Admin)"

    def get_help(self):
        """Returns a help string containing the configured available report types"""

        report_types = iter_to_str("\n    ".join(_REPORT_TYPES))

        helptext = f"""\
manage the various reports

Usage:
    manage [report type]
        
Available report types:
    {report_types}

Initializes a menu for reviewing and changing the status of current reports.
"""

        return helptext

    def func(self):
        report_type = self.cmdstring.split()[-1]
        if report_type == "reports":
            report_type = "players"
        if report_type not in _REPORT_TYPES:
            self.msg(f"'{report_type}' is not a valid report category.")
            return
        # remove the trailing s, just so everything reads nicer
        report_type = report_type[:-1]
        hub = _get_report_hub(report_type)
        if not hub:
            self.msg("You cannot manage that.")

        evmenu.EvMenu(
            self.account, menu, startnode="menunode_list_reports", hub=hub, persistent=True
        )


class ReportCmdBase(_DEFAULT_COMMAND_CLASS):
    """
    A parent class for creating report commands. This help text may be displayed if
    your command's help text is not properly configured.
    """

    help_category = "reports"
    # defines what locks the reports generated by this command will have set
    report_locks = "read:pperm(Admin)"
    # determines if the report can be filed without a target
    require_target = False
    # the message sent to the reporter after the report has been created
    success_msg = "Your report has been filed."
    # the report type for this command, if different from the key
    report_type = None

    def at_pre_cmd(self):
        """validate that the needed hub script exists - if not, cancel the command"""
        hub = _get_report_hub(self.report_type or self.key)
        if not hub:
            # a return value of True from `at_pre_cmd` cancels the command
            return True
        self.hub = hub
        return super().at_pre_cmd()

    def parse(self):
        """
        Parse the target and message out of the arguments.
        
        Override if you want different syntax, but make sure to assign `report_message` and `target_str`.
        """
        # do the base MuxCommand parsing first
        super().parse()
        # split out the report message and target strings
        if self.rhs:
            self.report_message = self.rhs
            self.target_str = self.lhs
        else:
            self.report_message = self.lhs
            self.target_str = ""

    def target_search(self, searchterm, **kwargs):
        """
        Search for a target that matches the given search term. By default, does a normal search via the
        caller - a local object search for a Character, or an account search for an Account.

        Args:
            searchterm (str) - The string to search for

        Returns:
            result (Object, Account, or None) - the result of the search
        """
        return self.caller.search(searchterm)

    def create_report(self, *args, **kwargs):
        """
        Creates the report. By default, this creates a Msg with any provided args and kwargs.

        Returns:
            success (bool) - True if the report was created successfully, or False if there was an issue.
        """
        return create.create_message(*args, **kwargs)

    def func(self):
        hub = self.hub
        if not self.args:
            self.msg("You must provide a message.")
            return

        target = None
        if self.target_str:
            target = self.target_search(self.target_str)
            if not target:
                return
        elif self.require_target:
            self.msg("You must include a target.")
            return

        receivers = [hub]
        if target:
            receivers.append(target)

        if self.create_report(
            self.account, self.report_message, receivers=receivers, locks=self.report_locks, tags=["report"]
        ):
            # the report Msg was successfully created
            self.msg(self.success_msg)
        else:
            # something went wrong
            self.msg(
                "Something went wrong creating your report. Please try again later or contact staff directly."
            )


# The commands below are the usable reporting commands


class CmdBug(ReportCmdBase):
    """
    file a bug

    Usage:
        bug [<target> =] <message>

    Note: If a specific object, location or character is bugged, please target it for the report.

    Examples:
        bug hammer = This doesn't work as a crafting tool but it should
        bug every time I go through a door I get the message twice
    """

    key = "bug"
    report_locks = "read:pperm(Developer)"


class CmdReport(ReportCmdBase):
    """
    report a player

    Usage:
        report <player> = <message>

    All player reports will be reviewed.
    """

    key = "report"
    report_type = "player"
    require_target = True
    account_caller = True


class CmdIdea(ReportCmdBase):
    """
    submit a suggestion

    Usage:
        ideas
        idea <message>

    Example:
        idea wouldn't it be cool if we had horses we could ride
    """

    key = "idea"
    aliases = ("ideas",)
    report_locks = "read:pperm(Builder)"
    success_msg = "Thank you for your suggestion!"

    def func(self):
        # we add an extra feature to this command, allowing you to see all your submitted ideas
        if self.cmdstring == "ideas":
            # list your ideas
            if (
                ideas := Msg.objects.search_message(sender=self.account, receiver=self.hub)
                .order_by("-db_date_created")
                .exclude(db_tags__db_key="closed")
            ):
                # todo: use a paginated menu
                self.msg(
                    "Ideas you've submitted:\n  "
                    + "\n  ".join(
                        f"|w{item.message}|n (submitted {datetime_format(item.date_created)})"
                        for item in ideas
                    )
                )
            else:
                self.msg("You have no open suggestions.")
            return
        # proceed to do the normal report-command functionality
        super().func()


class ReportsCmdSet(CmdSet):
    key = "Reports CmdSet"

    def at_cmdset_creation(self):
        super().at_cmdset_creation()
        if "bugs" in _REPORT_TYPES:
            self.add(CmdBug)
        if "ideas" in _REPORT_TYPES:
            self.add(CmdIdea)
        if "players" in _REPORT_TYPES:
            self.add(CmdReport)
        self.add(CmdManageReports)