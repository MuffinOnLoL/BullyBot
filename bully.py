import discord
from discord.ext import commands
from discord import option
import re
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import io
import os
import bisect
from datetime import datetime, timedelta
import calendar
from discord.ui import Button, View
from dotenv import load_dotenv
import asyncio

load_dotenv()
intents = discord.Intents.default()
intents.members = True
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)
#Mumbo jumbo just pulls libraries and initializes the bot perms/commands


#Storage File:
SCHEDULE_FILE = "schedule.json"

#Google Drive Setup:
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'bullybot-442505-5ec4ee963848.json'
FOLDER_ID = '1r95UcnUalduZOEK_cR2bLpKorQfrGKKN'

#These pull the credentials from the corresponding file DO NOT TOUCH THESE
credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes = SCOPES)
drive_service = build('drive', 'v3', credentials = credentials)

#These are the corresponding role numbers in the MSU Esports Server ALSO DONT TOUCH
team_captain_role = 738801488134144062
esports_coord_role = 907864828499083264
warden_role = 1235042369670352956
assist_esports_role = 1258127745045626993

#Put role permissions here for command access. All allowed = commands such as book and remove Admin = dump command
ALL_ALLOWED_ROLES = [team_captain_role, esports_coord_role, assist_esports_role, warden_role]
ADMIN_ROLES = [esports_coord_role, warden_role]

#This lists the current rosters of games as well as the max amount of teams per game. List appropriate games/colors below
ALLOWED_GAMES = sorted([
    "Apex", "CS", "DBD", "Deadlock", "Dota", "FGC", "Fortnite Build", "Fortnite Zero Build", "Halo", "Marvel Rivals", "EACFB 25", "LoL", 
    "Overwatch", "R6", "Rocket League", "Smash Dawgs", "Smite", "Valorant", "Splatoon"
])
ALLOWED_TEAMS = ["Maroon", "White", "Black", "Gray"]

#Creates the buttons for the schedule command
class DayButton(Button):
    def __init__(self, day: int, month: int, year: int, row: int, label: str = None):
        custom_id = f"day_{day}_{month}_{year}"
        super().__init__(label=label if label else str(day), style=discord.ButtonStyle.secondary, row = row, custom_id=custom_id)
        self.day = day
        self.month = month
        self.year = year

    async def callback(self, interaction: discord.Interaction):
        selected_date = f"{self.month:02}-{self.day:02}-{self.year}"
        #Retrieve reservations for that date
        reservations = [res for res in load_reservations() if res['date'] == selected_date]

        #Launch time select
        time_selection_view = timeSelectionView(selected_date, reservations, is_start_time=True)

        if interaction.response.is_done():
            await interaction.followup.send(
            f"You selected: **{selected_date}**\nPlease select a **Start Time**:", view = time_selection_view, ephemeral=True
            )
        else:
            await interaction.response.send_message(
            f"You selected: **{selected_date}**\nPlease select a **Start Time**:", view = time_selection_view, ephemeral=True
            )

#Creates the view of buttons when using /schedule and controls their actions
class CalendarView(View):
    def __init__(self, year: int, month: int, week_index: int = 0):
        super().__init__(timeout=180)
        self.year = year
        self.month = month
        self.week_index = week_index
        self.update_week_buttons()
    
    def update_week_buttons(self):
        self.clear_items()
        cal = calendar.monthcalendar(self.year, self.month)
        day_abbr = calendar.day_abbr
        self.week_index = max(0, min(self.week_index, len(cal) - 1))
        today = datetime.now().date()

        week = cal[self.week_index]

        for i, day in enumerate(week[:5]):
            if day == 0:
                self.add_item(Button(label="--", style=discord.ButtonStyle.gray, disabled=True, row=0))
            else:
                day_date = datetime(self.year, self.month, day).date()
                is_disabled = day_date <= today  # Disable for today or past dates

                # Add button
                self.add_item(
                    DayButton(
                        day=day,
                        month=self.month,
                        year=self.year,
                        row=0,
                        label=f"{day_abbr[i]} {day}"
                    ) if not is_disabled else
                    Button(
                        label=f"{day_abbr[i]} {day}",
                        style=discord.ButtonStyle.gray,
                        disabled=True,
                        row=0
                    )
                )
        for i, day in enumerate(week[5:]):
            if day == 0:
                self.add_item(Button(label= "--", style = discord.ButtonStyle.gray, disabled =True, row = 1))
            else:
                day_date = datetime(self.year, self.month, day).date()
                is_disabled = day_date <= today  # Disable for today or past dates
                # Add button
                self.add_item(
                    DayButton(
                        day=day,
                        month=self.month,
                        year=self.year,
                        row=1,
                        label=f"{day_abbr[i+5]} {day}"
                    ) if not is_disabled else
                    Button(
                        label=f"{day_abbr[i+5]} {day}",
                        style=discord.ButtonStyle.gray,
                        disabled=True,
                        row=1
                    )
                )
        self.add_item(Button(label="<< Previous Week", style=discord.ButtonStyle.primary, row=2, custom_id="prev_week"))
        self.add_item(Button(label="Next Week >>", style=discord.ButtonStyle.primary, row=2, custom_id="next_week"))
        self.add_item(Button(label="<< Previous Month", style=discord.ButtonStyle.secondary, row=3, custom_id="prev_month"))
        self.add_item(Button(label="Next Month >>", style=discord.ButtonStyle.secondary, row=3, custom_id="next_month"))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return True
    async def on_timeout(self):
        self.clear_items()

    async def handle_callback(self, interaction: discord.Interaction, action: str):
        cal = calendar.monthcalendar(self.year, self.month)
        if action == "prev_week":
            self.week_index -= 1
            if self.week_index < 0:
                self.month -= 1
                if self.month < 1:
                    self.month = 12
                    self.year -= 1
                cal = calendar.monthcalendar(self.year, self.month)
                self.week_index = len(cal) - 1   
        elif action == "next_week":
            self.week_index += 1
            if self.week_index >= len(cal):
                self.month += 1
                if self.month > 12:
                    self.month = 1
                    self.year += 1
                cal = calendar.monthcalendar(self.year, self.month)
                self.week_index = 0
        elif action == "prev_month":
            self.month -= 1
            if self.month < 1:
                self.month = 12
                self.year -= 1
            self.week_index = 0
        elif action == "next_month":
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1
            self.week_index = 0

        self.update_week_buttons()
        await interaction.response.edit_message(
            content = f"**{calendar.month_name[self.month]} {self.year} - Week {self.week_index + 1}**", view = self
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        action = interaction.data["custom_id"]
        await self.handle_callback(interaction, action)
        return True

#Creates the buttons when selecting a start/end time
class TimeButton(Button):
    def __init__(self, time_float: float, availability: str, row: int, available_pcs: int = None):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        time_label = datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M")
        custom_id = f"time_{time_float:.2f}"

        if availability == "unavailable":
            button_style = discord.ButtonStyle.grey
            disabled = True
        elif availability == "partial":
            button_style = discord.ButtonStyle.secondary
            disabled = False
        else:
            button_style = discord.ButtonStyle.success
            disabled = False

        super().__init__(label=time_label, style=button_style, row=row, custom_id=custom_id, disabled = disabled)
        self.time_float = time_float

    async def callback(self, interaction: discord.Interaction):
        selected_time = self.time_float
        await self.view.handle_time_selection(interaction, selected_time)

#Controls the look and actions of the time buttons
class timeSelectionView(View):
    def __init__(self, date: str, reservations: list, is_start_time: bool, start_time: float = None):
        super().__init__(timeout=300)
        self.date = date
        self.reservations = reservations
        self.is_start_time = is_start_time
        self.start_time = start_time
        self.generate_time_buttons()

    def generate_time_buttons(self):
        self.clear_items()
        reserved_slots = self.get_reserved_times()
        
        start_hour = 17
        end_hour = 23
        row = 0

        # Generate time in increments of 30 minutes
        for idx, time_float in enumerate(
            [h + (m / 60.0) for h in range(start_hour, int(end_hour) + 1) for m in [0, 30]]
        ):

            # Skip invalid times (end time cannot be before start time) THIS PREVENTS AFTER 10:00PM
            if self.is_start_time and time_float >=22.5:
                continue
            if not self.is_start_time and time_float > 23.0:
                continue
            if not self.is_start_time and self.start_time and time_float <= self.start_time:
                continue

            total_pcs = 10
            booked_pcs = sum(
                res['pcs']
                for res in self.reservations
                if res['time'] <= time_float < res['time'] + res['duration']
            )
            available_pcs = total_pcs - booked_pcs
            if available_pcs <= 0: 
                availablilty = "unavailable"
            elif available_pcs < total_pcs:
                availablilty = "partial"
            else:
                availablilty = "available"

            # Add button to the correct row
            self.add_item(TimeButton(time_float, availablilty, row, available_pcs))
            if (idx + 1) % 4 == 0:  # 4 buttons per row
                row += 1  # Move to the next row

    def get_reserved_times(self):
        reserved = set()
        for res in self.reservations:
            time_float = res['time']
            duration = res['duration']
            for i in range(int(duration * 2)):
                reserved.add(time_float + (i * 0.5))
        return reserved
    
    async def handle_time_selection(self, interaction: discord.Interaction, selected_time: float):
        if self.is_start_time:
            #Set start and proceed
            self.start_time = selected_time
            self.is_start_time = False
            self.generate_time_buttons()
            await interaction.response.edit_message(
                content=f"Start Time Selected: **{self.format_time(self.start_time)}**\nNow select an **End Time**:", view = self,
            )
        else:
            end_time = selected_time
            if end_time <= self.start_time:
                await interaction.response.send_message(
                    "Error: End time must be after start time. Please select agaain.", ephemeral=True
                )
                return
            duration = end_time - self.start_time
            reservations = load_reservations()
            pc_selection_view = PCSelectionView(self.date, self.start_time, duration, reservations)

            await interaction.response.edit_message(
                content=f"Time Selected: **{self.format_time(self.start_time)}** - **{self.format_time(end_time)}**\n"
                        "Please select the **number of PCs** to reserve:",
                view=pc_selection_view,
            )



    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60) 
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M")

#Creates the buttons to reserve # of pcs
class PCButton(Button):
    def __init__(self, pcs: int, is_disabled: bool, row: int):
        super().__init__(
            label = f"{pcs}",
            style = discord.ButtonStyle.success if not is_disabled else discord.ButtonStyle.danger,
            row = row,
            disabled = is_disabled,
            custom_id=f"pc_{pcs}",
        )
        self.pcs = pcs

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_pc_selection(interaction, self.pcs)

#Controls pc button functionality and looks
class PCSelectionView(View):
    def __init__(self, date: str, start_time: float, duration: float, reservations:list):
        super().__init__(timeout=300)
        self.date = date
        self.start_time = start_time
        self.duration = duration
        self.reservations = reservations
        self.available_pcs = self.calculate_available_pcs()
        self.generate_pc_buttons()

    def calculate_available_pcs(self):
        #Calculate pcs available
        total_pcs = 10
        booked_pcs = 0
        for res in self.reservations:
            if res['date'] == self.date:
                res_start = res['time']
                res_end = res_start + res['duration']
            #check overlap
                if not (self.start_time >= res_end or (self.start_time + self.duration) <= res_start):
                    booked_pcs += res['pcs']
        return max(0, total_pcs - booked_pcs)

    def generate_pc_buttons(self):
        self.clear_items()
        row = 0
        for pcs in range (1, 11):
            is_disabled = pcs > self.available_pcs
            self.add_item(PCButton(pcs, is_disabled, row))
            if pcs % 5 ==0:
                row += 1

    async def handle_pc_selection(self, interaction: discord.Interaction, pcs: int):
        self.reservation_data = {
            "date": self.date,
            "time": self.start_time,
            "duration": self.duration,
            "pcs": pcs,
        }
        game_view = GameSelectionView(self.reservation_data)

        await interaction.response.edit_message(
            content=f"PCs Selected: **{pcs}**\nNow select the **Game**:",
            view=game_view,
        )


    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float%1)*60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M")

#Creates buttons to select the appropriate game
class GameButton(Button):
    def __init__(self, game_name: str, row: int):
        super().__init__(label=game_name, style=discord.ButtonStyle.primary, row = row)
        self.game_name = game_name

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_game_selection(interaction, self.game_name)

#Controls functionality of game buttons
class GameSelectionView(View):
    def __init__(self, reservation_data:dict):
        super().__init__(timeout = 300)
        self.reservation_data = reservation_data
        self.generate_game_buttons()

    def generate_game_buttons(self):
        self.clear_items()
        row = 0
        for i, game in enumerate(ALLOWED_GAMES + ["Maintenance", "Event"]):
            self.add_item(GameButton(game, row = row))
            if (i + 1) % 5 == 0: 
                row += 1
    
    async def handle_game_selection(self, interaction: discord.Interaction, game_name: str):
        await interaction.response.defer(ephemeral=True)
        if game_name == "Event":
            #prompt name input if event was selected
            await interaction.followup.send("You selected **Event**. Please type the event name below:", ephemeral = True)
            
            #Wait for response
            def check(m):
                return m.author == interaction.user and m.channel == interaction.channel

            try:
                msg = await bot.wait_for("message", check=check, timeout=60)
                self.reservation_data["game"] = msg.content #Set event name as game
                self.reservation_data["team"] = "MSU Esports" #Default team for events
                reservation_list = load_reservations()
                reservation_list.append(self.reservation_data)
                save_reservations(reservation_list)

                await interaction.followup.send(
                    content=(
                        f"**Event Scheduled by {interaction.user.mention}!**\n"
                        f"Event: **{msg.content}**\n"
                        f"Date: **{self.reservation_data['date']}**\n"
                        f"Time: **{self.format_time(self.reservation_data['time'])}**\n"
                        f"Duration: **{self.reservation_data['duration']} hours**\n"
                        f"PCs Reserved: **{self.reservation_data['pcs']}**"
                    ),
                )
            except asyncio.TimeoutError:
                await interaction.followup.send(
                    "Response timed out. Please reinput.", ephemeral=True
                )

        elif game_name == "Maintenance":
            #Skip team selection for maintenance and proceed
            self.reservation_data["game"] = "Maintenance"
            self.reservation_data["team"] = "MSU Esports"  # Default team for maintenance
            reservation_list = load_reservations()
            reservation_list.append(self.reservation_data)
            save_reservations(reservation_list)

            await interaction.followup.send(
                content=(
                    f"**Maintenance Scheduled by {interaction.user.mention}!**\n"
                    f"Date: **{self.reservation_data['date']}**\n"
                    f"Time: **{self.format_time(self.reservation_data['time'])}**\n"
                    f"Duration: **{self.reservation_data['duration']} hours**\n"
                    f"PCs Reserved: **{self.reservation_data['pcs']}**"
                ),
            )
        else:
            #Regular games proceed as usual
            self.reservation_data["game"] = game_name
            team_view= TeamSelectionView(game_name,self.reservation_data)
            await interaction.followup.edit_message(
            interaction.message.id,
            content=f"**{game_name}** selected. Please choose a team:",
            view=team_view,
        )

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M %p")

#Creates buttons to select team colors
class TeamButton(Button):
    def __init__(self, team_name: str, row: int):
        super().__init__(label = team_name, style=discord.ButtonStyle.primary, row = row)
        self.team_name = team_name
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_team_selection(interaction, self.team_name)

#Controls team buttons functionality
class TeamSelectionView(View):
    def __init__(self, selected_game: str, reservation_data: dict):
        super().__init__(timeout=300)
        self.reservation_data = reservation_data
        self.generate_team_buttons()

    def generate_team_buttons(self):
        self.clear_items()
        row = 0
        for i, team in enumerate(ALLOWED_TEAMS):
            self.add_item(TeamButton(team, row = row))
            if (i + 1) % 2 == 0:
                row += 1
    
    async def handle_team_selection(self, interaction: discord.Interaction, team_name: str):

        self.reservation_data["team"] = team_name
 
        reservation_list = load_reservations()
        reservation_list.append(self.reservation_data)
        save_reservations(reservation_list)

        # Try to edit the message or handle expired interaction
        try:
        # Check if interaction has already been responded to
            if interaction.response.is_done():
                await interaction.followup.send(
                    "Reservation completed! A public confirmation has been posted.",
                    ephemeral=True,
                )
            else:
                await interaction.response.edit_message(
                    content="Reservation completed! A public confirmation has been posted.",
                    view=None,
                )
        except discord.errors.NotFound:
            # Handle expired interaction
            await interaction.followup.send(
                "The interaction has expired. Please restart the process.", ephemeral=True
            )
            return

        await interaction.channel.send(
            content=(
                f"**Reservation Confirmed by {interaction.user.mention}!**\n"
                f"Date: **{self.reservation_data['date']}**\n"
                f"Time: **{self.format_time(self.reservation_data['time'])}**\n"
                f"Duration: **{self.reservation_data['duration']} hours**\n"
                f"PCs Reserved: **{self.reservation_data['pcs']}**\n"
                f"Game: **{self.reservation_data['game']}**\n"
                f"Team: **{team_name}**"
            )
        )

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M")

#Creates the button for current matches
class MatchButton(Button):
    def __init__(self, match:dict, index: int):
        super().__init__(label=f"{match['game']} - {match['team']} ({match['date']})", style = discord.ButtonStyle.danger)
        self.match = match
        self.index = index
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_match_selection(interaction, self.index)

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1)* 60)
        return f"{hours}:{minutes:02}"

#Controls matches button functionality
class MatchSelectionView(View):
    def __init__(self, matches: list, remover: discord.Member):
        super().__init__(timeout=300)
        self.matches = matches
        self.remover = remover
        self.generate_match_buttons()

    def generate_match_buttons(self):
        self.clear_items()
        row = 0
        for idx, match in enumerate(self.matches):
            self.add_item(MatchButton(match, idx))
            if (idx+1)%4 == 0:
                row +=1

    async def handle_match_selection(self, interaction: discord.Interaction, index: int):
        removed_match = self.matches.pop(index)
        reservation_list = load_reservations()
        reservation_list.remove(removed_match)
        save_reservations(reservation_list)
        await interaction.channel.send(content=f"**{interaction.user.mention} removed the match:**\n"
                                               f"Game: **{removed_match['game']}**\n"
                                               f"Team: **{removed_match['team']}**\n"
                                               f"Date: **{removed_match['date']}**\n"
                                               f"Time: **{self.format_time(removed_match['time'])}**", view=None)
        # Confirm removal to the user
        await interaction.response.edit_message(content = "Match removed successfully!", view = None)

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return f"{hours}:{minutes:02}"

#Creates buttons to select days from schedule
class ScheduleDayButton(Button):
    def __init__(self, day: int, month: int, year: int, reservations: list, row: int, label: str = None):
        custom_id = f"schedule_day_{day}_{month}_{year}"
        self.day = day
        self.month = month
        self.year = year
        self.reservations = reservations

        # Style determination based on reservations
        total_reserved_pcs = sum(res['pcs'] for res in reservations if res['date'] == f"{month:02}-{day:02}-{year}")
        style = (
            discord.ButtonStyle.success
        )
        day_abbr = calendar.day_abbr[datetime(year, month, day).weekday()]
        super().__init__(
            label=label if label else f"{day_abbr} {day}",
            style=style,
            row=row,
            custom_id=custom_id
        )

    async def callback(self, interaction: discord.Interaction):
        selected_date = f"{self.month:02}-{self.day:02}-{self.year}"
        day_reservations = [res for res in load_reservations() if res['date'] == selected_date]

        if not day_reservations:
            #Display no matches are scheduled
            if interaction.response.is_done():
                await interaction.followup.send(
                    content=f"**No current matches for {selected_date}**",
                    ephemeral=True
                )
            else:
                await interaction.response.send_message(
                    content=f"**No current matches for {selected_date}**",
                    ephemeral=True
                )
        else:
            # Show matches for selected date
            match_view = MatchListView(selected_date, day_reservations)

            if interaction.response.is_done():
                # If the interaction is already responded to, use followup
                await interaction.followup.send(
                    content=f"**Matches for {selected_date}:**",
                    view=match_view,
                    ephemeral=True
                )
            else:
                # Otherwise, respond normally
                await interaction.response.edit_message(
                    content=f"**Matches for {selected_date}:**",
                    view=match_view
                )

#Creates look of the matches and functionality
class MatchListView(View):
    def __init__(self, date: str, matches: list):
        super().__init__(timeout=300)
        self.date = date
        self.matches = matches
        self.generate_match_buttons()

    def generate_match_buttons(self):
        self.clear_items()
        total_pcs = 10

        # Create buttons for matches on the selected date
        for idx, match in enumerate(sorted(self.matches, key=lambda m: m['time'])):
            start_time = self.format_time(match['time'])
            end_time = self.format_time(match['time'] + match['duration'])
            available_pcs = total_pcs - match['pcs']

            label = f"{match['game']} ({match['team']})\n{start_time} - {end_time} | {match['pcs']} PCs Reserved"
            button_style = (
                discord.ButtonStyle.danger if available_pcs <= 0 else
                discord.ButtonStyle.secondary if available_pcs < total_pcs else
                discord.ButtonStyle.success
            )

            self.add_item(
                Button(label=label, style=button_style, disabled=True)
            )

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M %p")

#Creates the look of actual schedule and functionality
class ScheduleCalendarView(View):
    def __init__(self, year: int, month: int, reservations: list, week_index: int = 0):
        super().__init__(timeout=300)
        self.year = year
        self.month = month
        self.reservations = reservations
        self.week_index = week_index
        self.update_week_buttons()

    def update_week_buttons(self):
        self.clear_items()
        cal = calendar.monthcalendar(self.year, self.month)
        day_abbr = calendar.day_abbr
        self.week_index = max(0, min(self.week_index, len(cal) - 1))
        today = datetime.now().date()

        # Loop through days of the week to create buttons
        week = cal[self.week_index]
        for i, day in enumerate(week[:5]):  # First row: Monday to Friday
            if day == 0:
                self.add_item(Button(label="--", style=discord.ButtonStyle.gray, disabled=True, row=0))
            else:
                day_date = datetime(self.year, self.month, day).date()
                day_reservations = [res for res in self.reservations if res['date'] == f"{self.month:02}-{day:02}-{self.year}"]
                total_reserved_pcs = sum(res['pcs'] for res in day_reservations)

                # Determine style for the button
                style = (
                    discord.ButtonStyle.danger if total_reserved_pcs >= 10 else
                    discord.ButtonStyle.secondary if total_reserved_pcs > 0 else
                    discord.ButtonStyle.success
                )

                # Add day button, making past dates clickable
                self.add_item(
                    ScheduleDayButton(
                        day=day,
                        month=self.month,
                        year=self.year,
                        reservations=self.reservations,
                        row=0,
                        label=f"{day_abbr[i]} {day}"
                    )
                )

        for i, day in enumerate(week[5:]):  # Second row: Saturday and Sunday
            if day == 0:
                self.add_item(Button(label="--", style=discord.ButtonStyle.gray, disabled=True, row=1))
            else:
                day_date = datetime(self.year, self.month, day).date()
                day_reservations = [res for res in self.reservations if res['date'] == f"{self.month:02}-{day:02}-{self.year}"]
                total_reserved_pcs = sum(res['pcs'] for res in day_reservations)

                # Determine style for the button
                style = (
                    discord.ButtonStyle.danger if total_reserved_pcs >= 10 else
                    discord.ButtonStyle.secondary if total_reserved_pcs > 0 else
                    discord.ButtonStyle.success
                )

                # Add day button, making past dates clickable
                self.add_item(
                    ScheduleDayButton(
                        day=day,
                        month=self.month,
                        year=self.year,
                        reservations=self.reservations,
                        row=1,
                        label=f"{day_abbr[i+5]} {day}"
                    )
                )

        # Add navigation buttons
        self.add_item(Button(label="<< Previous Week", style=discord.ButtonStyle.primary, row=2, custom_id="prev_week"))
        self.add_item(Button(label="Next Week >>", style=discord.ButtonStyle.primary, row=2, custom_id="next_week"))
        self.add_item(Button(label="<< Previous Month", style=discord.ButtonStyle.secondary, row=3, custom_id="prev_month"))
        self.add_item(Button(label="Next Month >>", style=discord.ButtonStyle.secondary, row=3, custom_id="next_month"))

    async def handle_navigation(self, interaction: discord.Interaction, action: str):
        cal = calendar.monthcalendar(self.year, self.month)

        if action == "prev_week":
            self.week_index -= 1
            if self.week_index < 0:
                self.month -= 1
                if self.month < 1:
                    self.month = 12
                    self.year -= 1
                cal = calendar.monthcalendar(self.year, self.month)
                self.week_index = len(cal) - 1
        elif action == "next_week":
            self.week_index += 1
            if self.week_index >= len(cal):
                self.month += 1
                if self.month > 12:
                    self.month = 1
                    self.year += 1
                cal = calendar.monthcalendar(self.year, self.month)
                self.week_index = 0
        elif action == "prev_month":
            self.month -= 1
            if self.month < 1:
                self.month = 12
                self.year -= 1
            self.week_index = 0
        elif action == "next_month":
            self.month += 1
            if self.month > 12:
                self.month = 1
                self.year += 1
            self.week_index = 0

        self.update_week_buttons()
        await interaction.response.edit_message(
            content=f"**{calendar.month_name[self.month]} {self.year} - Week {self.week_index + 1}**",
            view=self
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        action = interaction.data.get("custom_id", "")
        await self.handle_navigation(interaction, action)
        return True
    
    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M %p")

    def generate_match_buttons(self):
        self.clear_items()
        start = self.page * self.page_size
        end = start + self.page_size
        current_matches = self.matches[start:end]

        for idx, match in enumerate(current_matches):
            self.add_item(MatchButton(match, start + idx))

        #Navigation buttons if there are enough matches to navigate
        if self.page > 0:
            self.add_item(Button(label=" << Previous", style = discord.ButtonStyle.primary, row = 1, custom_id="prev_page"))
        if end < len(self.matches):
            self.add_item(Button(label="Next >>", style = discord.ButtonStyle.primary, row=1, custom_id="next_page"))

#Creates and controls a paging system for remove command matches
class PagingRemoveView(View):
    def __init__(self, matches: list, remover: discord.Member, page: int = 0, page_size: int = 5):
        super().__init__(timeout=300)
        self.matches = matches
        self.remover = remover
        self.page = page
        self.page_size = page_size
        self.generate_match_buttons()

    def generate_match_buttons(self):
        self.clear_items()
        start = self.page * self.page_size
        end = start + self.page_size
        current_matches = self.matches[start:end]

        for idx, match in enumerate(current_matches):
            self.add_item(MatchButton(match, start + idx))

        # Navigation buttons if there are enough matches to navigate
        if self.page > 0:
            self.add_item(Button(label="<< Previous", style=discord.ButtonStyle.primary, row=1, custom_id="prev_page"))
        if end < len(self.matches):
            self.add_item(Button(label="Next >>", style=discord.ButtonStyle.primary, row=1, custom_id="next_page"))

    async def handle_match_selection(self, interaction: discord.Interaction, index: int):
        # Handle match removal logic
        removed_match = self.matches.pop(index)
        reservation_list = load_reservations()
        reservation_list.remove(removed_match)
        save_reservations(reservation_list)

        # Notify the channel about the removed match
        await interaction.channel.send(
            content=f"**{interaction.user.mention} removed the match:**\n"
                    f"Game: **{removed_match['game']}**\n"
                    f"Team: **{removed_match['team']}**\n"
                    f"Date: **{removed_match['date']}**\n"
                    f"Time: **{self.format_time(removed_match['time'])}**",
        )

        # Confirm removal to the user
        await interaction.response.edit_message(content="Match removed successfully!", view=None)

    async def handle_nav(self, interaction: discord.Interaction, action: str):
        if action == "prev_page":
            self.page -= 1
        elif action == "next_page":
            self.page += 1

        self.generate_match_buttons()
        await interaction.response.edit_message(
            content="Select a match to remove:",
            view=self,
        )

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return f"{hours}:{minutes:02}"

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        action = interaction.data.get("custom_id", "")
        if action in {"prev_page", "next_page"}:
            await self.handle_nav(interaction, action)
        return True

#Creates a view for all current rosters and controls functionality
class GameRosterView(View):
    def __init__(self, allowed_games):
        super().__init__(timeout=300)
        self.allowed_games = allowed_games
        self.generate_game_buttons()

    def generate_game_buttons(self):
        self.clear_items()
        for game in self.allowed_games:
            self.add_item(GameRosterButton(game))

#Creates a button for all current rosters
class GameRosterButton(Button):
    def __init__(self, game_name):
        super().__init__(label = game_name, style=discord.ButtonStyle.primary)
        self.game_name = game_name

    async def callback(self, interaction: discord.Interaction):
        guild = interaction.guild
        team_colors = ALLOWED_TEAMS
        staff_role_name = f"{self.game_name} Staff"
        coach_role_name = f"{self.game_name} Coach"

        roster_data = {"Staff": [], "Coach": [], "Teams": {color: [] for color in team_colors}}

        staff_role = discord.utils.get(guild.roles, name = staff_role_name)
        coach_role = discord.utils.get(guild.roles, name = coach_role_name)

        if staff_role:
            roster_data["Staff"] = [
                member.display_name for member in guild.members if staff_role in member.roles
            ]

        if coach_role:
            roster_data["Coach"] = [
                member.display_name for member in guild.members if coach_role in member.roles
            ]
        
        for color in team_colors:
            role_name = f"{self.game_name} {color}"
            role = discord.utils.get(guild.roles, name=role_name)

            if role:
                roster_data["Teams"][color] = [
                    member.display_name for member in guild.members if role in member.roles
                ]
            else:
                roster_data[color] = []     

        #Search all users for corresponding roles
        for color in team_colors:
            role_name = f"{self.game_name} {color}"
            role = discord.utils.get(guild.roles, name = role_name)
            if role:
                roster_data[color] = [
                    member.display_name for member in guild.members if role in member.roles
                ]
            else:
                roster_data[color] = []

        #Format message
        roster_message = f"**Roster for {self.game_name}:**\n"

        # Add Game Coaches
        coach_list = ", ".join(roster_data["Coach"]) if roster_data["Coach"] else "No coaches assigned"
        roster_message += f"**Game Coaches**: {coach_list}\n"

        # Add Game Staff
        staff_list = ", ".join(roster_data["Staff"]) if roster_data["Staff"] else "No staff assigned"
        roster_message += f"**Game Staff**: {staff_list}\n\n"


        for color, members in roster_data["Teams"].items():
            member_list = ", ".join(members) if members else "No members on this roster"
            roster_message += f"**{color}**: {member_list}\n"

        await interaction.response.send_message(content=roster_message, ephemeral=True)

#Creates a paging system to view multiple pages of staff
class StaffPagingView(View):
    def __init__(self, staff_data):
        super().__init__(timeout = 300)
        self.staff_data = staff_data
        self.page = 0
        self.generate_page()

    def generate_page(self):
        self.clear_items()
        self.add_item(Button(label = "<< Previous", style = discord.ButtonStyle.primary, custom_id="prev_staff_page", disabled = (self.page==0)))
        self.add_item(Button(label="Next >>", style=discord.ButtonStyle.primary, custom_id="next_staff_page", disabled=(self.page == 1)))

    async def handle_paging(self, interaction:discord.Interaction, action: str):
        if action == "prev_staff_page":
            self.page -= 1
        elif action == "next_staff_page":
            self.page += 1
        
        staff_message = "**Staff Members**\n\n"

        if self.page == 0:
            #This is the first page with exec/board/warden
            staff_message += "**Executive Committee**\n"
            for role, members in self.staff_data["Executive Roles"].items():
                member_list = ", ".join(members) if members else "No Members"
                staff_message += f"**{role}**: {member_list}\n"

            staff_message += "**\nBoard of Directors**\n"
            for role, members in self.staff_data["Board Roles"].items():
                member_list = ", ".join(members) if members else "No Members"
                staff_message += f"**{role}**: {member_list}\n"

            warden_list = ", ".join(self.staff_data["Warden"]) if self.staff_data["Warden"] else "No Wardens"
            staff_message += f"\n**Warden**: {warden_list}\n"

        elif self.page == 1:
            #These are the remaining roles not listed above
            if self.staff_data["Media Team"]:
                staff_message += "**Media Team**\n"
                staff_message += ", ".join(self.staff_data["Media Team"]) + "\n"

            if self.staff_data["Event Committee"]:
                staff_message += "\n**Event Committee**\n"
                staff_message += ", ".join(self.staff_data["Event Committee"]) + "\n"

            if self.staff_data["Stream Team"]:
                staff_message += "\n**Stream Team**\n"
                staff_message += ", ".join(self.staff_data["Stream Team"]) + "\n"

            if self.staff_data["Tabling Crew"]:
                staff_message += "\n**Tabling Crew**\n"
                staff_message += ", ".join(self.staff_data["Tabling Crew"]) + "\n"

            if self.staff_data["Tryout Coords"]:
                staff_message += "\n**Tryout Coordinators**\n"
                staff_message += ", ".join(self.staff_data["Tryout Coords"]) + "\n"

            if self.staff_data["Head Moderators"]:
                staff_message += "\n**Head Moderators**\n"
                staff_message += ", ".join(self.staff_data["Head Moderators"]) + "\n"

            if self.staff_data["Moderators"]:
                staff_message += "\n**Moderators**\n"
                staff_message += ", ".join(self.staff_data["Moderators"]) + "\n"

        self.generate_page()
        await interaction.response.edit_message(content=staff_message, view=self)            

    @discord.ui.button(label="<< Previous", style=discord.ButtonStyle.primary, row=1)
    async def previous_button(self, button: Button, interaction: discord.Interaction):
        await self.handle_paging(interaction, "prev_staff_page")

    @discord.ui.button(label="Next >>", style=discord.ButtonStyle.primary, row=1)
    async def next_button(self, button: Button, interaction: discord.Interaction):
        await self.handle_paging(interaction, "next_staff_page")

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        print(f"INTERACTION ReCEIVED {interaction.data['custom_id']}")
        action = interaction.data["custom_id"]
        await self.handle_paging(interaction,action)
        return True

#Checks to see if the user is one of the following roles
def check_perm(allowed_roles):
    async def predicate(ctx: discord.ApplicationContext):
        user_roles = [role.id for role in ctx.author.roles]
        if any(role in allowed_roles for role in user_roles):
            print("User has permission")
            return True
        await ctx.respond("You do not have permission to use this command.", ephemeral = True)
        return False
    return commands.check(predicate)
def is_admin(allowed_roles):
    async def predicate(ctx: discord.ApplicationContext):
        user_roles = [role.id for role in ctx.author.roles]
        if any(role in allowed_roles for role in user_roles):
            print("User has admin permission")
            return True
        await ctx.respond("You do not have permission to use this command.", ephemeral = True)
        return False
    return commands.check(predicate)

#Checks to see if the date is in the future and passes if so
def validate_future_date(date_str):
    try:
        input_date = datetime.strptime(date_str, "%m-%d")
        current_year = datetime.now().year
        input_date = input_date.replace(year = current_year)
        today = datetime.now()
        return input_date > today
    except ValueError:
        return False

#Load/Pull reservations from JSON file
def load_reservations():
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE, "r") as file:
                return json.load(file)
        except FileNotFoundError:
            print("[INFO] Schedule file not found, starting with an empty list.")
            return []
        except json.JSONDecodeError as e:
            print(f"[ERROR] Failed to decode JSON: {e}")
            return []
    else:
        print("[INFO] Schedule file not found locally. Attempting to download from Google Drive")
        return download_from_drive()

#Save/push reservations to JSON file
def save_reservations(reservations):
    try:
        with open(SCHEDULE_FILE, "w") as file:
            json.dump(reservations, file, indent=4)
        print("[INFO] Reservations successfully written to schedule.json")
        # Debug: Read back the file to confirm
        upload_to_drive()
    except Exception as e:
        print(f"[ERROR] Failed to write to schedule.json: {e}")

#Push the local JSON to JSON located on google drive
def upload_to_drive():
    try:
        media = MediaFileUpload(SCHEDULE_FILE, mimetype = 'application/json')

        results = drive_service.files().list(
            q = f"'{FOLDER_ID}' in parents and name = '{SCHEDULE_FILE}'", fields = "files(id, name)"
        ).execute()
        files = results.get('files', [])

        if files:
            file_id = files[0]['id']
            drive_service.files().update(fileId = file_id, media_body = media).execute()
            print("[INFO] Schedule file uploaded to Google Drive.")
        else:
            file_metadata = {'name': SCHEDULE_FILE, 'parents': [FOLDER_ID]}
            drive_service.files().create(body=file_metadata, media_body=media).execute()
            print("[INFO] Schedule file uploaded to Google Drive.")
    except Exception as e:
        print(f"[ERROR] Failed to upload to Google Drive: {e}")

#Pull the google drive JSON to local JSON
def download_from_drive():
    try:
        results = drive_service.files().list(
            q = f"'{FOLDER_ID}' in parents and name = '{SCHEDULE_FILE}'", fields = "files(id, name)").execute()
        files = results.get('files', [])
        
        if not files:
            print("[INFO] No schedule file found on Google Drive. Starting Fresh.")
            return []
        
        file_id = files[0]['id']
        request = drive_service.files().get_media(fileId = file_id)
        fh = io.BytesIO()
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()

        fh.seek(0)
        with open(SCHEDULE_FILE, 'wb') as f:
            f.write(fh.read())
        print("[INFO] Schedule file downloaded from Google Drive.")

        with open(SCHEDULE_FILE, "r") as file:
            return json.load(file)
    except Exception as e:
        print(f"[ERROR] Failed to download from Google Drive: {e}")
        return []

#Load the current list from local JSON
reservation_list = load_reservations()

#Simply announce that the bot is correctly running
@bot.event
async def on_ready():
    print(f'Bot {bot.user} is ready!')

#Parse the date to determine it is a valid time (DEPRECATED/UNUSED)
def validate_date(date_str):
    # Regular expression to match MM-DD format
    pattern = r'^\d{2}-\d{2}$'
    if re.match(pattern, date_str):
        month, day = map(int, date_str.split('-'))
        # Check if the month is between 1 and 12, and the day is valid for the month
        if 1 <= month <= 12 and 1 <= day <= 31:
            return True
    return False

#Sort matches appropriately on JSON in calendar format    
def reservation_sort_key(match):
    return datetime.strptime(match['date'], '%m-%d'), match['time']

#Autofill game/suggest game while typing (DEPRECATED/UNUSED)
async def game_autocomplete(ctx: discord.AutocompleteContext):
    current = ctx.value.lower() if ctx.value else ""
    suggestions = [
        game for game in ALLOWED_GAMES if current in game.lower()]
    return (suggestions[:25])

#Autofill team/suggest team while typing (DEPRECATED/UNUSED)
async def team_autocomplete(ctx: discord.AutocompleteContext):
    current = ctx.value.lower() if ctx.value else ""
    suggestions = [
        team for team in ALLOWED_TEAMS if current in team.lower()]
    return suggestions[:25]

#Books a match and pushes to the JSON. Only accessible by ALL_ALLOWED_ROLES
@bot.slash_command(description="Schedule a future match")
@check_perm(ALL_ALLOWED_ROLES)
async def book(interaction: discord.ApplicationContext):
    #Pulls the current time as to prevent scheduling the day of and in the past
    today = datetime.now()
    year, month = today.year, today.month
    cal = calendar.monthcalendar(year, month)
    currentday = today.day
    current_week = next(
        (index for index, week in enumerate(cal) if currentday in week), 0)
    
    #Creates a calendar view for simple/clear selection 
    view = CalendarView(year = year, month = month, week_index=current_week)
    #Send match calendar as a response
    await interaction.response.send_message(F"**{calendar.month_name[month]} {year}**", view = view, ephemeral=True)

# Command to display scheduled reservations
@bot.slash_command(description="Display scheduled matches")
async def schedule(interaction: discord.ApplicationContext):
    # Load reservations from the JSON file
    reservations = load_reservations()
    
    # Get today's date and calculate the current week
    today = datetime.now()
    year, month = today.year, today.month
    cal = calendar.monthcalendar(year, month)
    current_day = today.day
    current_week = next((index for index, week in enumerate(cal) if current_day in week), 0)

    # Initialize the ScheduleCalendarView with the current date and reservations
    view = ScheduleCalendarView(year, month, reservations, current_week)
    
    # Send the calendar view as a response
    await interaction.response.send_message(
        content=f"**{calendar.month_name[month]} {year} - Week {current_week + 1}**",
        view=view,
        ephemeral=True
    )

# Command to remove a match
@bot.slash_command(description="Remove a scheduled match")
@check_perm(ALL_ALLOWED_ROLES)
async def remove(interaction: discord.ApplicationContext):
    #Filter reservations for future matches
    today = datetime.now().date()
    reservation_list = [
        res for res in load_reservations()
        if datetime.strptime(res["date"], "%m-%d-%Y").date() >= today
    ]
    #If no future matches display an error
    if not reservation_list:
        await interaction.respond("No matches scheduled", ephemeral = True)
        return
    
    #Display the view of current future matches otherwise
    view = PagingRemoveView(reservation_list, interaction.user)
    await interaction.respond("Select a match to remove:", view= view, ephemeral = True)

#Dumps the current contents of the local/drive JSON completely. Only accessible by ADMIN_ROLES and must be used carefully
@bot.slash_command(description = "Dump the reservation list (DO NOT USE UNLESS SURE)")
@is_admin(ADMIN_ROLES)
async def dump(interaction: discord.ApplicationContext):
    #Pull reservations and display error if none are found
    reservation_list = load_reservations()
    if not reservation_list:
        await interaction.respond("No reservations found.", ephemeral = True)
        return
    #Display a button that the user must confirm before dumping
    class ConfirmClearView(View):
        def __init__(self, timeout=30):
            super().__init__(timeout = timeout)
            self.value = None
        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
        async def confirm_button(self, button: Button, inter: discord.Interaction):
            #Once it is confirmed, clear list and send a confirmation message with who dumped the list
            reservation_list.clear()
            save_reservations(reservation_list)
            await inter.channel.send(
                content=(
                    f"**Reservation list has been dumped by {interaction.user.mention}!**"
                )
            )

            #Display that the list has been completely cleared to user
            await inter.response.send_message("All reservations have been cleared.", ephemeral = True)
            self.stop()
        #Create a button to cancel the clear if needed
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_button(self, button: Button, inter: discord.Interaction):
            #Alert user the operation was canceled
            await inter.response.send_message("Operation canceled.", ephemeral = True)
            self.stop()

    #Display to the user that they must accept the clear and display confirm/cancel buttons
    view = ConfirmClearView()
    await interaction.respond("Are you absolutely sure you want to clear all reservations? This can not be undone.", view = view, ephemeral = True)
    await view.wait()

#A custom command that displays information about *moi* and some extra info about commands available
@bot.slash_command(description = "Display author and information related to the bot.")
async def credits(interaction: discord.ApplicationContext):
    #Creates an embed to send in appropriate chat
    embed = discord.Embed(
        title = "Bot Credits/Info",
        description = "More information about the bot and its creator.",
        color = discord.Color.blue()
    )
    #Add a field that displays author info/name
    embed.add_field(
        name = "Author",
        value = "Colin Klein\nMuffinOnLoL",
        inline=False
    )
    #Display a paragraph detailing the commands and how the bot works in code
    embed.add_field(
        name = "How the bot works",
        value = (
            "This bot was created in order to schedule and manage reservations for the Esports lab.\n"
            "It utilizes a few different commands such as:\n"
            "- /book Booking matches\n"
            "- /remove Removing matches\n"
            "- /schedule Displaying scheduling\n"
            "- /dump Emptying the list of matches\n"
            "- /rosters Displays the current rosters\n"
            "- /staff Displays the current staff\n"
            "- /credits Displays the current information\n"
            "Currently the bot writes the information to a local dictionary using Python.\n"
            "It then pushes that data to a json file that is then pushed to a google drive folder.\n"
            "This allows the information to be retrieved from numerous recpients and for the bot itself.\n"
            "Lastly, it features an interactive scheduling system to simplify the booking process."
        ),
        inline = False
    )
    #Then adds a thank you note for those who view the command
    embed.set_footer(
        text="Thank you for using my bot! Please reach out to Muffin for any questions, concerns, or feedback!"
    )
    await interaction.response.send_message(embed = embed, ephemeral = True)

#Display the current rosters at MSU Esprots
@bot.slash_command(description = "Display a current roster for a game")
async def rosters(interaction: discord.ApplicationContext):
    #Displays all current titles available for the user to select
    view = GameRosterView(allowed_games=ALLOWED_GAMES)
    await interaction.response.send_message("Select a game to view its roster", view = view, ephemeral = True)

#Lists all current active staff at MSU Esports
@bot.slash_command(description = "Lists all current staff positions")
async def staff(interaction: discord.ApplicationContext):

    #THESE ARE CURRENT ROLES THAT ARE ACTIVE IN MSU ESPORTS 24-25
    #Change/add these when needed
    exec_roles = [
        "President", "Vice President", "Secretary", "Treasurer", "Esports Director"
    ]
    board_roles = [
        "Assistant Esports Director", "Event Director", "Media Director", "Outreach Director", "Stream Director"
    ]
    ward_role = "Warden"
    head_mod_role = "Head Moderator"
    moderator_role = "Moderator"
    media_role = "Media Team"
    tryout_coord = "Tryouts Coordinator"
    event_comm_role = "Event Committee"
    tabling_crew_role = "Tabling Crew"
    stream_team_role = "Stream Team"

    #Pull the current user base inside server
    guild = interaction.guild
    await guild.fetch_members().flatten()

    #Create a dictionary to store all users with the following roles
    staff_data = {
        "Executive Roles": {role: [] for role in exec_roles},
        "Board Roles": {role: [] for role in board_roles},
        "Media Team": [],
        "Event Committee": [],
        "Stream Team": [],
        "Tabling Crew": [],
        "Tryout Coords": [],
        "Warden": [],
        "Head Moderators": [],
        "Moderators": []
    }

    #For each of the folloiwng roles, if a certain role add to the correct dictionary key
    for role_name in exec_roles + board_roles + [media_role] + [tryout_coord] + [ward_role] + [tabling_crew_role] + [stream_team_role] + [event_comm_role] + [head_mod_role] + [moderator_role]:
        role = discord.utils.get(guild.roles, name = role_name)
        if role:
            for member in guild.members:
                if role in member.roles:
                    if role_name in exec_roles:
                        staff_data["Executive Roles"][role_name].append(member.display_name)
                    elif role_name in board_roles:
                        staff_data["Board Roles"][role_name].append(member.display_name)
                    elif role_name == media_role:
                        staff_data["Media Team"].append(member.display_name)
                    elif role_name == tryout_coord:
                        staff_data["Tryout Coords"].append(member.display_name)
                    elif role_name == ward_role:
                        staff_data["Warden"].append(member.display_name)
                    elif role_name == tabling_crew_role:
                        staff_data["Tabling Crew"].append(member.display_name)
                    elif role_name == stream_team_role:
                        staff_data["Stream Team"].append(member.display_name)
                    elif role_name == event_comm_role:
                        staff_data["Event Committee"].append(member.display_name)
                    elif role_name == head_mod_role:
                        staff_data["Head Moderators"].append(member.display_name)
                    elif role_name == moderator_role:
                        staff_data["Moderators"].append(member.display_name)

    view = StaffPagingView(staff_data)

    #Format staff list
    staff_message = "**Staff Members**\n\n"
    staff_message += "**Executive Committee**\n"
    for role, members in staff_data["Executive Roles"].items():
        member_list = ", ".join(members) if members else "No Members"
        staff_message += f"**{role}**: {member_list}\n"

    # Add Board Roles
    staff_message += "\n**Board of Directors**\n"
    for role, members in staff_data["Board Roles"].items():
        member_list = ", ".join(members) if members else "No Members"
        staff_message += f"**{role}**: {member_list}\n"

    warden_list = ", ".join(staff_data["Warden"]) if staff_data["Warden"] else "No Wardens"
    staff_message += f"**\nWarden**: {warden_list}\n"    

    # Send the response
    await interaction.response.send_message(content=staff_message, ephemeral = True, view = view)

#Finally, run the stupid bot and pray to God
bot.run(os.getenv("MY_TOKEN"))