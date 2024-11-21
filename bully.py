import discord
from discord.ext import commands
from discord import option
from datetime import datetime
import re


intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='/', intents=intents)

# Sample storage (can be replaced with a database)
reservation_list = []

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
    await interaction.respond(f"Match for {team} scheduled on {date} from {time} - {end_time} using {pcs} pcs!")

# Command to display scheduled reservations
@bot.slash_command(description="Display scheduled matches")
async def schedule(interaction: discord.ApplicationContext):
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
    # Search for the match in the reservation_list
    match_found = False
    for match in reservation_list:
        if match['team1'] == team1 and match['date'] == date:
            reservation_list.remove(match)
            match_found = True
            await interaction.response.send_message(f"Match for {team1} on {date} has been removed.")
            break

    if not match_found:
        await interaction.response.send_message(f"No match found for {team1} on {date}.")


