import discord
from discord.ext import commands
from discord import option
from datetime import datetime
import re
import json
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
from google.oauth2.service_account import Credentials
import io
import os
import bisect
from datetime import datetime
from discord.ui import Button, View

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
    "Apex", "CS", "DBD", "Dota", "FGC", "Fortnite", "Halo", "LoL", "NCAA", 
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
# Command to schedule a match with auto-completion
@bot.slash_command(description="Schedule a match")
@is_team_captain()
async def book(
    interaction: discord.ApplicationContext,
    game: str = discord.Option(description="Game title (ACTIVE ROSTER)", autocomplete = game_autocomplete),
    team: str = discord.Option(description="Team name", autocomplete = team_autocomplete),
    date: str = discord.Option(description="Date of the match (MM-DD)"),
    time: int = discord.Option(description="Start time of the match (HH:MM MUST BE 5 OR LATER)"),
    duration: int = discord.Option(description="Duration of the match in hours (MUST END BEFORE 11)"),
    pcs: int = discord.Option(description="Number of PCs to reserve")
):
    await interaction.response.defer()
    try:
        if ':' not in time:
            await interaction.followup.send("Time must be in HH:MM format.")
            return

        hours, minutes = map(int, time.split(':'))
        if minutes not in [0, 15, 30, 45]:
            await interaction.followup.send("Minutes must be 0, 15, 30, or 45.")
            return
        
        time_float = hours + minutes / 60.0
        duration = float(duration)
        pcs = int(pcs)
    except ValueError:
        await interaction.followup.send("Invalid input! Time, duration, and PCs must be numbers.")
        return
    if game not in ALLOWED_GAMES:
        await interaction.followup.send(
            f"Invalid Game selected. Please enter an active roster.", ephemeral=True)
        return
    if team not in ALLOWED_TEAMS:
        await interaction.followup.send(
            f"Invalid Team selected. Please select from the options.", ephemeral = True)
        return
    if not validate_date(date):
        print(f"Invalid date format provided: {date}")  # Debug print
        await interaction.followup.send("Invalid date format. Please input as MM-DD")
        return
    if not validate_future_date(date):
        await interaction.followup.send(
            f"The date must be at least one day in the future.", ephemeral = True)
        return

    # Validate that the time is 5 or later
    if time_float < 5 or time_float >= 10:
        await interaction.followup.send("Invalid time! Please choose a time that is 5 or later.")
        return  # Exit the command if the time is invalid
    # Define the end time for the new reservation
    end_time = time_float + duration

    #THIS DETERMINES THE ENDTIME FOR SCHEDULING
    if end_time > 11.00:
        await interaction.followup.send("Endtime must be before 11PM")
        return

    # Check current reservations that overlap with the same date and time range
    total_pcs = 0
    for match in reservation_list:
        if match['date'] == date:
            existing_start = match['time']
            existing_end = match['time'] + match['duration']
            # Check for overlap:
            if (time_float < existing_end and end_time > existing_start):
                total_pcs += match['pcs']

    # Add the new reservation's pcs to the total
    total_pcs += pcs

    # Check if total PCs exceed the maximum limit
    if total_pcs > 10:
        await interaction.respond("Maximum of 10 PCs reservations reached for this time/day. Please choose another time or date.")
        return  # Exit the command if the limit is reached

    match = {
        'game': game,
        'team': team,
        'date': date,
        'time': time_float,
        'duration': duration,
        'pcs': pcs
    }

    index = bisect.bisect_left([reservation_sort_key(m) for m in reservation_list], reservation_sort_key(match))
    reservation_list.insert(index, match)# Add match to list or save to a database
    save_reservations(reservation_list)
    start_time_str = f"{int(time_float)}:{int((time_float % 1) * 60):02}"
    end_time_str = f"{int(end_time)}:{int((end_time % 1) * 60):02}"
    await interaction.respond(f"Match for {game} scheduled on {date} from {start_time_str} - {end_time_str} using {pcs} pcs!")



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
async def remove(
    interaction: discord.ApplicationContext,
    game: str = discord.Option(description="Name of the team", autocomplete = game_autocomplete), 
    team: str = discord.Option(description="Team name", autocomplete = team_autocomplete),
    date: str = discord.Option(description="Date of the match (MM-DD format)")
):
    await interaction.response.defer()

    reservation_list = load_reservations()
    # Search for the match in the reservation_list
    match_found = False
    for match in reservation_list:
        if match['game'] == game and match['team'] == team and match['date'] == date:
            reservation_list.remove(match)
            save_reservations(reservation_list)
            match_found = True
            await interaction.followup.send(f"Match for {game} on {date} has been removed.")
            break

    if not match_found:
        await interaction.followup.send(f"No match found for {game} on {date}.")

@bot.slash_command(description = "Dump the reservation list (DO NOT USE UNLESS SURE)")
@is_esports_coord()
async def dump(interaction: discord.ApplicationContext):
    reservationlist = load_reservations()
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
            await inter.response.send_message("All reservations have been cleared.", ephemeral = True)
            self.stop()
        @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
        async def cancel_button(self, button: Button, inter: discord.Interaction):
            await inter.response.send_message("Opeartion canceled.", ephemeral = True)
            self.stop()

    view = ConfirmClearView()
    await interaction.respond("Are you absolutely sure you want to clear all reservations? This can not be undone.", view = view)

    await view.wait()
        

