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
    

# Command to schedule a match with auto-completion
@bot.slash_command(description="Schedule a match")
async def book(
    interaction: discord.ApplicationContext,
    team: str = discord.Option(description="Name of the first team"),
    date: str = discord.Option(description="Date of the match (MM-DD)"),
    time: int = discord.Option(description="Start time of the match (24-hour format)"),
    duration: int = discord.Option(description="Duration of the match in hours"),
    pcs: int = discord.Option(description="Number of PCs to reserve")
):
    try:
        time = int(time)
        duration = int(duration)
        pcs = int(pcs)
    except ValueError:
        await interaction.response.send_message("Invalid input! Time, duration, and PCs must be numbers.")
        return
    if not validate_date(date):
        print(f"Invalid date format provided: {date}")  # Debug print
        await interaction.respond("Invalid date format. Please input as MM-DD")
        return
    # Validate that the time is 5 or later
    if time < 5:
        await interaction.respond("Invalid time! Please choose a time that is 5 or later.")
        return  # Exit the command if the time is invalid

    # Define the end time for the new reservation
    end_time = time + duration

    # Check current reservations that overlap with the same date and time range
    total_pcs = 0
    for match in reservation_list:
        if match['date'] == date:
            existing_start = match['time']
            existing_end = match['time'] + match['duration']
            # Check for overlap:
            if (time < existing_end and end_time > existing_start):
                total_pcs += match['pcs']

    # Add the new reservation's pcs to the total
    total_pcs += pcs

    # Check if total PCs exceed the maximum limit
    if total_pcs > 10:
        await interaction.respond("Maximum of 10 PCs reservations reached for this time/day. Please choose another time or date.")
        return  # Exit the command if the limit is reached

    match = {
        'team1': team,
        'date': date,
        'time': time,
        'duration': duration,
        'pcs': pcs
    }
    reservation_list.append(match)  # Add match to list or save to a database
    save_reservations(reservation_list)
    await interaction.respond(f"Match for {team} scheduled on {date} from {time} - {end_time} using {pcs} pcs!")

# Command to display scheduled reservations
@bot.slash_command(description="Display scheduled matches")
async def schedule(interaction: discord.ApplicationContext):
    reservation_list = load_reservations()
    if not reservation_list:
        await interaction.respond("No matches scheduled.")
    else:
        response = "Upcoming Matches:\n"
        for match in reservation_list:
            time2 = match['time'] + match['duration']
            response += f"{match['team1']} - {match['date']} from {match['time']}-{time2} - {match['pcs']} pcs\n"
        await interaction.respond(response)


# Command to remove a match
@bot.slash_command(description="Remove a scheduled match")
async def remove(
    interaction: discord.ApplicationContext,
    team1: str = discord.Option(description="Name of the first team"),
    date: str = discord.Option(description="Date of the match (MM-DD format)")
):
    reservation_list = load_reservations()
    # Search for the match in the reservation_list
    match_found = False
    for match in reservation_list:
        if match['team1'] == team1 and match['date'] == date:
            reservation_list.remove(match)
            save_reservations(reservation_list)
            match_found = True
            await interaction.response.send_message(f"Match for {team1} on {date} has been removed.")
            break

    if not match_found:
        await interaction.response.send_message(f"No match found for {team1} on {date}.")


