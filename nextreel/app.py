# Import required libraries
import random
import os
import time
import pymysql
import imdb
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from nextreel.scripts.getMovieFromIMDB import get_filtered_random_row, main, fetch_movie_info_from_imdb
from flask_login import LoginManager, login_user, login_required, logout_user, current_user, UserMixin
from db_config import db_config, user_db_config
from nextreel.scripts.getUserAccount import get_watched_movie_posters, get_watched_movies, get_watched_movie_details, \
    get_all_watched_movie_details_by_user
from nextreel.scripts.logMovieToAccount import log_movie_to_account
from scripts.mysql_query_builder import execute_query
from queue import Queue, Empty
import threading

# Initialize Flask app
app = Flask(__name__)
app.secret_key = 'some_random_secret_key'  # IMPORTANT: Change this in production

# Initialize Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)

# Variable to determine whether a user should be logged out when the home page loads
should_logout_on_home_load = True


# User class to handle login sessions
class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username


# Initialize a global queue to hold movie data
movie_queue = Queue(maxsize=3)


# Function to populate the movie queue
def populate_movie_queue():
    # Infinite loop to keep the queue populated
    while True:
        # If queue size is less than 2, fetch a new movie
        if movie_queue.qsize() < 2:
            # Get a random movie that matches the criteria (empty in this case)
            row = get_filtered_random_row(db_config, {})
            tconst = row['tconst']
            # Fetch detailed movie information from IMDb
            movie = fetch_movie_info_from_imdb(tconst)
            # Create a dictionary with relevant movie details

            movie_data = {
                "title": movie.get('title', 'N/A'),
                "imdb_id": movie.getID(),
                "genres": ', '.join(movie.get('genres', ['N/A'])),
                "directors": ', '.join([director['name'] for director in movie.get('director', [])]),
                "writers": next((writer['name'] for writer in movie.get('writer', []) if 'name' in writer), "N/A"),
                "cast": ', '.join([actor['name'] for actor in movie.get('cast', [])][:3]),
                "runtimes": ', '.join(movie.get('runtimes', ['N/A'])),
                "countries": ', '.join(movie.get('countries', ['N/A'])),
                "languages": ', '.join(movie.get('languages', ['N/A'])),
                "rating": movie.get('rating', 'N/A'),
                "votes": movie.get('votes', 'N/A'),
                "plot": movie.get('plot', ['N/A'])[0],
                "poster_url": movie.get_fullsizeURL()
            }

            # Put the fetched movie into the global queue
            movie_queue.put(movie_data)
            # Pause for 1 second to prevent rapid API calls
        time.sleep(1)


# Start a thread to populate the movie queue
# Start a background thread to populate the movie queue
populate_thread = threading.Thread(target=populate_movie_queue)
populate_thread.daemon = True  # Set the thread as a daemon
populate_thread.start()


@app.route('/account_settings')
@login_required
def account_settings():
    # Fetch the watched movie posters for the current user
    watched_movie_posters = get_watched_movie_posters(current_user.id, user_db_config)

    # Initialize an empty list to store the details for each watched movie
    watched_movie_details_list = []

    # Fetch all watched movie details for the current user
    watched_movie_details = get_all_watched_movie_details_by_user(current_user.id)

    # Append each movie's details to the list
    for details in watched_movie_details:
        watched_movie_details_list.append(details)
        print(watched_movie_details_list)

    # Render the account settings template
    return render_template('userAccountSettings.html',
                           poster_urls=watched_movie_posters,
                           watched_movie_details=watched_movie_details_list)


# Function to load user details during login
@login_manager.user_loader
def load_user(user_id):
    # Query to fetch user details from the database
    user_data = execute_query(user_db_config, "SELECT * FROM users WHERE id=%s", (user_id,))
    # If user data exists, return a User object
    if user_data:
        return User(id=user_data['id'], username=user_data['username'])
    # Otherwise, return None
    return None


# Print the current working directory (for debugging)
print("Current working directory:", os.getcwd())

# Declare a global variable to store the last displayed movie
global last_displayed_movie


# Home route
@app.route('/')
def home():
    global should_logout_on_home_load
    # Logout the user if the flag is set
    if should_logout_on_home_load:
        logout_user()
        should_logout_on_home_load = False
    # Fetch a movie from the global queue
    movie_data = movie_queue.get()
    # Update the global variable with the fetched movie data
    global last_displayed_movie
    last_displayed_movie = movie_data
    # Render the home page with the fetched movie data
    return render_template('home.html', movie=movie_data, current_user=current_user)


# Login route
@app.route('/login', methods=['GET', 'POST'])
def login():
    # If user is already authenticated, redirect to home
    if current_user.is_authenticated:
        return redirect(url_for('home'))
    # If request method is POST, handle login
    if request.method == 'POST':
        # Fetch username and password from the form
        username = request.form['username']
        password = request.form['password']
        # Query to fetch user details
        conn = pymysql.connect(**user_db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)
        cursor.execute("SELECT * FROM users WHERE username=%s", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        # If user exists and password matches, log in the user
        if user_data and user_data['password'] == password:
            user = User(id=user_data['id'], username=user_data['username'])
            login_user(user)
            return redirect(url_for('home'))
        else:
            # If authentication fails, flash an error message
            flash("Invalid username or password")
    # Render the login template
    return render_template('userLogin.html')


# Route for logout
@app.route('/logout')
@login_required  # Require the user to be logged in to access this route
def logout():
    # Log the user out
    logout_user()
    # Redirect to the login page
    return redirect(url_for('login'))


# Route for user registration
@app.route('/register', methods=['GET', 'POST'])
def register():
    # If the user is already authenticated, redirect to home
    if current_user.is_authenticated:
        return redirect(url_for('home'))

    # If the request method is POST, process the registration form
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        email = request.form['email']

        # Connect to the database
        conn = pymysql.connect(**user_db_config)
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        # Execute the insert query
        cursor.execute("INSERT INTO users (username, email, password) VALUES (%s, %s, %s)", (username, email, password))

        # Commit the transaction
        conn.commit()
        cursor.close()
        conn.close()

        # Flash a success message
        flash("Registration successful! Please login.")

        # Redirect to the login page
        return redirect(url_for('login'))

    # Render the registration form
    return render_template('createAccountForm.html')


# Route for setting filters
@app.route('/setFilters')
def set_filters():
    # Render the filter settings template
    return render_template('setFilters.html')


# Route to get a random movie
@app.route('/random_movie', methods=['POST'])
def random_movie():
    # Redirect to the home route, where a random movie will be displayed
    return redirect(url_for('home'))


# Route to get a movie based on filters
@app.route('/filtered_movie', methods=['POST'])
def filtered_movie_endpoint():
    # Extract filter criteria from the form
    filters = request.form
    criteria = {}

    if filters.get('year_min'):
        criteria['min_year'] = int(filters.get('year_min'))
    if filters.get('year_max'):
        criteria['max_year'] = int(filters.get('year_max'))
    if filters.get('imdb_score_min'):
        criteria['min_rating'] = float(filters.get('imdb_score_min'))
    if filters.get('imdb_score_max'):
        criteria['max_rating'] = float(filters.get('imdb_score_max'))
    if filters.get('num_votes_min'):
        criteria['min_votes'] = int(filters.get('num_votes_min'))

        # Fetch the movie based on the criteria
    movie_info = main(criteria)

    # If no movies are found, return an error message
    if not movie_info:
        return "No movies found based on the given criteria."

    # Create a dictionary to hold movie details

    movie_data = {
        "title": movie_info.get('title', 'N/A'),
        "imdb_id": movie_info.getID(),
        "genres": ', '.join(movie_info.get('genres', ['N/A'])),
        # "directors": ', '.join([director['name'] for director in movie_info.get('director', [])]),
        "directors": ', '.join([director['name'] for director in movie_info.get('director', [])][:1]),
        "writer": movie_info.get('writer', [])[0]['name'] if movie_info.get('writer') else None,
        "cast": ', '.join([actor['name'] for actor in movie_info.get('cast', [])][:3]),
        "runtimes": ', '.join(movie_info.get('runtimes', ['N/A'])),
        "countries": ', '.join(movie_info.get('countries', ['N/A'])),
        "languages": ', '.join(movie_info.get('languages', ['N/A'])),
        "rating": movie_info.get('rating', 'N/A'),
        "votes": movie_info.get('votes', 'N/A'),
        "plot": movie_info.get('plot', ['N/A'])[0],
        "poster_url": movie_info.get_fullsizeURL()
    }
    print(movie_data)

    # Render the template with the filtered movie
    return render_template('filtered_movies.html', movie=movie_data)


# Route to mark a movie as seen
@app.route('/seen_it', methods=['POST'])
@login_required  # Require the user to be logged in
def seen_it():
    global last_displayed_movie  # Use the global variable to get the last displayed movie

    # If there is a last displayed movie, log it to the user's account
    if last_displayed_movie:
        tconst = last_displayed_movie.get("imdb_id")

        # Log the movie to the user's account
        log_movie_to_account(current_user.id, current_user.username, tconst, last_displayed_movie, user_db_config)

        # Redirect to the home page
        return redirect(url_for('home'))
    else:
        # Return an error if no movies are in the queue
        return jsonify({'status': 'failure', 'message': 'No movies in the queue'}), 400


# Entry point of the application
if __name__ == "__main__":
    # Run the Flask app in debug mode (change this in production)
    app.run(debug=True)
