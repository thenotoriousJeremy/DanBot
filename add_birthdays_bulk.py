import sqlite3

# Connect to the database
conn = sqlite3.connect('birthdays.db')
cursor = conn.cursor()

# Replace with the username or user ID of the entry to remove
user_id = 0  # Set this to the actual user ID if known
username = "burritodp"  # Replace with the username

# Delete the entry
try:
    cursor.execute("DELETE FROM birthdays WHERE user_id = ? OR username = ?", (user_id, username))
    if cursor.rowcount > 0:
        print(f"Successfully removed {username}'s birthday from the database.")
    else:
        print(f"No entry found for {username}.")
except Exception as e:
    print(f"Error removing entry: {e}")

# Commit changes and close the connection
conn.commit()
conn.close()
