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

load_dotenv()
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

#Storage File:
SCHEDULE_FILE = "schedule.json"

#Google Drive Setup:
SCOPES = ['https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'bullybot-442505-5ec4ee963848.json'
FOLDER_ID = '1r95UcnUalduZOEK_cR2bLpKorQfrGKKN'

credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes = SCOPES)
drive_service = build('drive', 'v3', credentials = credentials)

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

class GameButton(Button):
    def __init__(self, game_name: str, row: int):
        super().__init__(label=game_name, style=discord.ButtonStyle.primary, row = row)
        self.game_name = game_name

    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_game_selection(interaction, self.game_name)

class GameSelectionView(View):
    def __init__(self, reservation_data:dict):
        super().__init__(timeout = 300)
        self.reservation_data = reservation_data
        self.generate_game_buttons()

    def generate_game_buttons(self):
        self.clear_items()
        row = 0
        for i, game in enumerate(ALLOWED_GAMES):
            self.add_item(GameButton(game, row = row))
            if (i + 1) % 5 == 0:
                row += 1
    
    async def handle_game_selection(self, interaction: discord.Interaction, game_name: str):
        self.reservation_data["game"] = game_name

        # Prepare reservation data and transition to team selection
        team_view = TeamSelectionView(game_name, self.reservation_data)

        await interaction.response.edit_message(
            content=f"Game Selected: **{game_name}**\nNow select your **Team**:",
            view=team_view,
        )

class TeamButton(Button):
    def __init__(self, team_name: str, row: int):
        super().__init__(label = team_name, style=discord.ButtonStyle.primary, row = row)
        self.team_name = team_name
    
    async def callback(self, interaction: discord.Interaction):
        await self.view.handle_team_selection(interaction, self.team_name)

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
        await interaction.response.edit_message(
            content="Reservation completed! A public confirmation has been posted.",
            view=None,
    )

    @staticmethod
    def format_time(time_float: float):
        hours = int(time_float)
        minutes = int((time_float % 1) * 60)
        return datetime.strptime(f"{hours}:{minutes:02}", "%H:%M").strftime("%I:%M")

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

def is_team_captain():
    async def predicate(ctx: discord.ApplicationContext):
        team_captain_role = 738801488134144062
        if any(getattr(role, "id", None) == team_captain_role for role in ctx.author.roles):
            print("DEBUG: THIS WORKS")
            return True
        
        await ctx.respond("Only Team Captains may schedule/remove matches.", ephemeral = True)
        return False
    return commands.check(predicate)

def is_esports_coord():
    async def predicate(ctx: discord.ApplicationContext):
        esports_coord_role = 1235042369670352956
        if any(getattr(role, "id", None) == esports_coord_role for role in ctx.author.roles):
            return True
    return commands.check(predicate)

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

def save_reservations(reservations):
    try:
        with open(SCHEDULE_FILE, "w") as file:
            json.dump(reservations, file, indent=4)
        print("[INFO] Reservations successfully written to schedule.json")
        # Debug: Read back the file to confirm
        upload_to_drive()
    except Exception as e:
        print(f"[ERROR] Failed to write to schedule.json: {e}")

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

reservation_list = load_reservations()

@bot.event
async def on_ready():
    print(f'Bot {bot.user} is ready!')

def validate_date(date_str):
    # Regular expression to match MM-DD format
    pattern = r'^\d{2}-\d{2}$'
    if re.match(pattern, date_str):
        month, day = map(int, date_str.split('-'))
        # Check if the month is between 1 and 12, and the day is valid for the month
        if 1 <= month <= 12 and 1 <= day <= 31:
            return True
    return False
    
def reservation_sort_key(match):
    return datetime.strptime(match['date'], '%m-%d'), match['time']

ALLOWED_GAMES = sorted([
    "Apex", "CS", "DBD", "Deadlock", "Dota", "FGC", "Fortnite", "Halo", "Marvel Rivals", "NCAA", "LoL", 
    "OW", "Rainbow6", "RL", "Smash", "Smite", "Valorant"
])
ALLOWED_TEAMS = ["Maroon", "White", "Black", "Gray"]

async def game_autocomplete(ctx: discord.AutocompleteContext):
    current = ctx.value.lower() if ctx.value else ""
    suggestions = [
        game for game in ALLOWED_GAMES if current in game.lower()]
    return (suggestions[:25])

async def team_autocomplete(ctx: discord.AutocompleteContext):
    current = ctx.value.lower() if ctx.value else ""
    suggestions = [
        team for team in ALLOWED_TEAMS if current in team.lower()]
    return suggestions[:25]

@bot.slash_command(description="Schedule a future match")
@is_team_captain()
async def book(interaction: discord.ApplicationContext):
    today = datetime.now()
    year, month = today.year, today.month
    cal = calendar.monthcalendar(year, month)
    currentday = today.day
    current_week = next(
        (index for index, week in enumerate(cal) if currentday in week), 0)
    
    view = CalendarView(year = year, month = month, week_index=current_week)
    await interaction.response.send_message(F"**{calendar.month_name[month]} {year}**", view = view, ephemeral=True)

# Command to display scheduled reservations
@bot.slash_command(description="Display scheduled matches")
async def schedule(interaction: discord.ApplicationContext):
    reservation_list = load_reservations()
    if not reservation_list:
        await interaction.respond("No matches scheduled.")
        return
    else:

        embed = discord.Embed(
            title = "Upcoming Reservations",
            description = "Here are the matches scheduled:",
            color = discord.Color.blue()
        )
        for match in reservation_list:
            start_time_str = f"{int(match['time'])}:{int((match['time'] % 1) * 60):02}"
            end_time = match['time'] + match['duration']
            end_time_str = f"{int(end_time)}:{int((end_time % 1) * 60):02}"
            embed.add_field(
                name = f"{match['game']} ({match['team']})- {match['date']}",
                value = f"Time: {start_time_str} - {end_time_str}\nPCs Reserved: {match['pcs']}",
                inline = False
            )
        await interaction.response.send_message(embed=embed)

# Command to remove a match
@bot.slash_command(description="Remove a scheduled match")
@is_team_captain()
async def remove(interaction: discord.ApplicationContext):
    reservation_list = load_reservations()
    if not reservation_list:
        await interaction.respond("No matches scheduled.", ephemeral = True)
        return
    view = MatchSelectionView(reservation_list, interaction.user)
    await interaction.respond("Select a match to remove:", view=view, ephemeral = True)

@bot.slash_command(description = "Dump the reservation list (DO NOT USE UNLESS SURE)")
@is_esports_coord()
async def dump(interaction: discord.ApplicationContext):
    reservation_list = load_reservations()
    if not reservation_list:
        await interaction.respond("No reservations found.", ephemeral = True)
        return
    class ConfirmClearView(View):
        def __init__(self, timeout=30):
            super().__init__(timeout = timeout)
            self.value = None
        @discord.ui.button(label="Confirm", style=discord.ButtonStyle.danger)
        async def confirm_button(self, button: Button, inter: discord.Interaction):
            reservation_list.clear()
            save_reservations(reservation_list)
            await inter.channel.send(
                content=(
                    f"**Reservation list has been dumped by {interaction.user.mention}!**"
                )
            )

            await inter.response.send_message("All reservations have been cleared.", ephemeral = True)
            self.stop()
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_button(self, button: Button, inter: discord.Interaction):
            await inter.response.send_message("Opeartion canceled.", ephemeral = True)
            self.stop()

    view = ConfirmClearView()
    await interaction.respond("Are you absolutely sure you want to clear all reservations? This can not be undone.", view = view, ephemeral = True)

    await view.wait()
        
bot.run(os.getenv("MY_TOKEN"))