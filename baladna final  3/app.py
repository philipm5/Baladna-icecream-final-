import os
from calendar import monthrange
from datetime import datetime
import fitz  # PyMuPDF
import io
from flask import session
from PIL import Image
from flask import Flask, render_template, request, redirect, url_for, session, send_file, flash
from werkzeug.utils import secure_filename
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from werkzeug.security import generate_password_hash, check_password_hash
import config
from sqlalchemy import text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm import configure_mappers

app = Flask(__name__)
app.secret_key = 'your_secret_key'

# Configuration for upload folder
UPLOAD_FOLDER = 'static/admin_pics'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf'}

# Configuration for SQLAlchemy
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///employees.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Initialize the database and migration objects
db = SQLAlchemy(app)
migrate = Migrate(app, db)
configure_mappers()

# Define the Employee model
class Employee(db.Model):
    __tablename__ = 'employee'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String, nullable=False)
    monthly_salary = db.Column(db.Float, nullable=False)
    id_number = db.Column(db.String, nullable=False)
    phone_number = db.Column(db.String, nullable=False)
    address = db.Column(db.String, nullable=False)
    start_date = db.Column(db.Date, nullable=False)  # Corrected to store as Date type
    holidays_taken = db.Column(db.Integer, nullable=True, default=0)

    uploaded_files = db.relationship('UploadedFile', back_populates='employee', cascade='all, delete-orphan')

    def __init__(self, name, monthly_salary, id_number, phone_number, address, start_date, holidays_taken=0):
        self.name = name
        self.monthly_salary = monthly_salary
        self.id_number = id_number
        self.phone_number = phone_number
        self.address = address
        self.start_date = start_date
        self.holidays_taken = holidays_taken

    def __repr__(self):
        return f'<Employee {self.name}>'


# Define the UploadedFile model
class UploadedFile(db.Model):
    __tablename__ = 'uploaded_files'

    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('employee.id'), nullable=False)
    filename = db.Column(db.String(255), nullable=False)
    file_data = db.Column(db.LargeBinary, nullable=False)
    upload_date = db.Column(db.String(10), nullable=False)

    # Define the relationship to Employee
    employee = db.relationship('Employee', back_populates='uploaded_files')

    def __repr__(self):
        return f'<UploadedFile {self.filename} for Employee {self.employee_id}>'

# Ensure the upload folder exists
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# Custom number format filter for Jinja2
def number_format(value, decimal_places=2):
    return f"{float(value):,.{decimal_places}f}"

app.jinja_env.filters['number_format'] = number_format

# Function to check if a file is allowed
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# Function to calculate the equivalent number based on employee's extra hours
def calculate_equivalent_number(employee, extra_hours):
    salary_before = float(employee['monthly_salary'])
    num_days = monthrange(datetime.now().year, datetime.now().month)[1]
    salary_per_day = salary_before / num_days
    salary_per_hour = salary_per_day / 9
    return extra_hours * salary_per_hour

# Function to calculate the equivalent value of absent hours
def calculate_equivalent_absent_hours(employee, hours_absent):
    salary_before = float(employee['monthly_salary'])
    num_days = monthrange(datetime.now().year, datetime.now().month)[1]
    salary_per_day = salary_before / num_days
    salary_per_hour = salary_per_day / 9  # Assuming 9 working hours per day
    return hours_absent * salary_per_hour

@app.route('/')
def home():
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # Check if the provided username matches and verify the hashed password
        if username == config.ADMIN_USERNAME and check_password_hash(
                config.ADMIN_PASSWORD, password):
            session['admin'] = {
                'username': username
            }  # Store the admin username in the session
            return redirect(url_for('admin_dashboard'))
        else:
            flash("Invalid credentials, please try again.", "error")
    return render_template('login.html')

# Function to reindex employee IDs sequentially
def reindex_employees():
    try:
        # Fetch all employees ordered by current ID
        employees = Employee.query.order_by(Employee.id).all()
        current_id = 1

        # Check if the employees table is empty
        if not employees:
            # If empty, reset the autoincrement sequence to start from 1
            reset_autoincrement_sequence(0)
            print("Employee table is empty. Autoincrement sequence reset to 1.")
        else:
            # If not empty, reassign IDs based on row order
            for employee in employees:
                employee.id = current_id
                current_id += 1
            db.session.commit()
            # Set the sequence to the last used ID to ensure the next insert follows the correct order
            reset_autoincrement_sequence(current_id - 1)
            print(f"Reindexed employees. New ID sequence set to {current_id - 1}.")
            
    except Exception as e:
        print(f"Error reindexing employees: {e}")
        flash("An error occurred while reindexing employee IDs.", "danger")

# Function to reset the autoincrement sequence in SQLite
def reset_autoincrement_sequence(max_id):
    try:
        # Ensure SQLite's autoincrement sequence is set correctly
        db.session.execute(text("DELETE FROM sqlite_sequence WHERE name='employee';"))  # Note the table name correction
        if max_id > 0:
            db.session.execute(text(f"UPDATE sqlite_sequence SET seq = {max_id} WHERE name = 'employee';"))
        db.session.commit()
    except Exception as e:
        print(f"Error resetting autoincrement sequence: {e}")
        flash("An error occurred while resetting the autoincrement sequence.", "danger")

@app.route('/admin_dashboard', methods=['GET', 'POST'])
def admin_dashboard():
    if 'admin' not in session:
        return redirect(url_for('login'))

    admin = session['admin']  # Get the current admin from the session

    if request.method == 'POST':
        # Add Employee
        if 'add_employee' in request.form:
            name = request.form['name']
            monthly_salary = request.form.get('monthly_salary', type=float)
            phone_number = request.form['phone_number']
            id_number = request.form['id_number']
            start_date = request.form['start_date']
            address = request.form['address']

            try:
                # Convert the start date from string to a date object
                parsed_start_date = datetime.strptime(start_date, '%d/%m/%Y').date()
            except ValueError:
                flash("Invalid start date format. Please use DD/MM/YYYY.", "danger")
                return redirect(url_for('admin_dashboard'))

            # Create a new employee record
            new_employee = Employee(
                name=name,
                monthly_salary=monthly_salary,
                phone_number=phone_number,
                id_number=id_number,
                start_date=parsed_start_date,
                address=address,
                holidays_taken=0
            )

            try:
                db.session.add(new_employee)
                db.session.commit()

                # Create a directory for the new employee
                sanitized_name = name.replace(" ", "_")
                employee_directory = os.path.join('baladna final', 'static', 'info_database', 'employees', sanitized_name)
                if not os.path.exists(employee_directory):
                    os.makedirs(employee_directory)

                flash(f"Employee {name} added successfully and directory created!", "success")
            except Exception as e:
                print(f"Error adding employee: {e}")
                flash("An error occurred while adding the employee.", "danger")

        # Update Employee
        elif 'update_employee' in request.form:
            try:
                employee_id = int(request.form['employee_id'])
                new_salary = float(request.form['new_salary'])
                new_phone_number = request.form.get('new_phone_number')
                new_address = request.form.get('new_address')

                # Fetch the employee record and update it
                employee = Employee.query.get(employee_id)
                if employee:
                    employee.monthly_salary = new_salary
                    if new_phone_number:
                        employee.phone_number = new_phone_number
                    if new_address:
                        employee.address = new_address
                    db.session.commit()
                    flash(f"Employee {employee.name} updated successfully!", "success")
                else:
                    flash("Employee not found.", "danger")
            except ValueError:
                flash("Invalid data provided for updating employee.", "danger")
            except Exception as e:
                print(f"Error updating employee: {e}")
                flash("An error occurred while updating the employee.", "danger")

        # Delete Employee
        elif 'delete_employee' in request.form:
            try:
                # Parse the employee ID from the form
                employee_id = int(request.form['employee_id'])
                # Fetch the employee record from the database
                employee = Employee.query.get(employee_id)

                # Check if the employee exists
                if employee:
                    # Attempt to delete the employee
                    db.session.delete(employee)
                    db.session.commit()
                    flash(f"Employee {employee.name} deleted successfully!", "success")

                    # Reindex employees to maintain sequential IDs
                    reindex_employees()
                else:
                    flash("Employee not found.", "danger")
            
            except ValueError:
                flash("Invalid employee ID provided.", "danger")
            except Exception as e:
                # Log and display an error message if an unexpected issue occurs
                print(f"Error deleting employee: {e}")
                flash("An error occurred while deleting the employee.", "danger")

    # Fetch all employees from the database to display on the dashboard
    employees = Employee.query.all()
    return render_template('admin_dashboard.html', admin=admin, employees=employees)


@app.route('/settings', methods=['GET', 'POST'])
def settings():
    if 'admin' not in session:
        return redirect(url_for('login'))

    admins = session.get(
        'admins', [{
            'username': config.ADMIN_USERNAME,
            'password': generate_password_hash(config.ADMIN_PASSWORD),
            'picture': None
        }])

    if request.method == 'POST':
        if 'add_admin' in request.form:
            new_admin_username = request.form['username']
            new_admin_password = request.form['password']
            admin_picture = request.files['picture']

            if new_admin_username and new_admin_password and allowed_file(
                    admin_picture.filename):
                # Create a folder for the new admin
                admin_folder = os.path.join(app.config['UPLOAD_FOLDER'],
                                            new_admin_username)
                if not os.path.exists(admin_folder):
                    os.makedirs(admin_folder)

                # Save the picture in the admin's folder
                filename = secure_filename(admin_picture.filename)
                picture_path = os.path.join(admin_folder, filename)
                admin_picture.save(picture_path)

                hashed_password = generate_password_hash(new_admin_password)

                new_admin = {
                    'username': new_admin_username,
                    'password': hashed_password,
                    'picture': picture_path
                }

                admins.append(new_admin)

                session['admins'] = admins
                print(f"New admin added: {new_admin}"
                      )  # Debug: Confirm new admin details
                flash("Admin added successfully!", "success")
            else:
                flash(
                    "Failed to add admin. Ensure all fields are filled and the picture is valid.",
                    "danger")

        elif 'delete_admin' in request.form:
            admin_username = request.form['username']

            admins = [
                admin for admin in admins
                if admin['username'] != admin_username
            ]

            session['admins'] = admins
            flash("Admin deleted successfully!", "success")

    return render_template('settings.html', admins=admins)

@app.route('/employee_list')
def employee_list():
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch all employees from the database ordered by ID
    employees = Employee.query.order_by(Employee.id).all()

    # Format the start date and salary before passing it to the template
    for employee in employees:
        # Format the start date to "day/month/year" format
        employee.formatted_start_date = employee.start_date.strftime('%d/%m/%Y') if employee.start_date else "N/A"
        employee.formatted_salary = f"{float(employee.monthly_salary):,.2f}"

    return render_template('employee_list.html', employees=employees)

@app.route('/employee_history/<int:employee_id>', methods=['GET', 'POST'])
def employee_history(employee_id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch the employee from the database
    employee = Employee.query.get(employee_id)

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for('employee_list'))

    # Ensure formatted fields are set
    employee.formatted_start_date = employee.start_date.strftime('%d/%m/%Y') if employee.start_date else "N/A"
    employee.formatted_salary = f"{employee.monthly_salary:,.2f}"

    # Fetch uploaded files for the employee
    uploaded_files = UploadedFile.query.filter_by(employee_id=employee.id).all()
    print(f"Fetched uploaded files: {uploaded_files}")  # Debug print

    # Pass the employee and their uploaded files to the template
    return render_template('employee_history.html', employee=employee, uploaded_files=uploaded_files)

@app.route('/employee_details/<int:employee_id>', methods=['GET', 'POST'])
def employee_details(employee_id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch the employee directly from the database using the employee ID
    employee = Employee.query.get(employee_id)

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for('employee_list'))

    now = datetime.now()
    month = now.strftime('%B')
    number_of_days = monthrange(now.year, now.month)[1]

    # Salary calculations
    salary_before = float(employee.monthly_salary)
    salary_per_day = round(salary_before / number_of_days, 2)
    salary_per_hour = round(salary_per_day / 9, 2)

    # Initialize form data from session or set default values
    days_absent = session.get('days_absent', 0)
    hours_absent = session.get('hours_absent', 0)
    extra_days = session.get('extra_days', 0)
    extra_hours = session.get('extra_hours', 0)
    extra_hours_1_5 = session.get('extra_hours_1_5', 0)
    advanced_payment = session.get('advanced_payment', 0.0)
    holidays_taken = session.get('holidays_taken', 0)
    holidays_value = f"{holidays_taken}/14"

    # Calculate earnings from extra shifts at 1.5x rate
    extra_shifts_earnings = round(extra_hours_1_5 * salary_per_hour * 1.5, 2)

    # Calculate the updated salary after adjustments
    salary_after = (
        salary_before - advanced_payment - days_absent * salary_per_day -
        hours_absent * salary_per_hour + extra_days * salary_per_day +
        extra_hours * salary_per_hour + extra_shifts_earnings
    )
    salary_after = round(salary_after, 2)

    if request.method == 'POST':
        try:
            # Retrieve and convert form inputs, saving them temporarily in the session
            days_absent = int(request.form.get('days_absent', 0))
            hours_absent = int(request.form.get('hours_absent', 0))
            extra_days = int(request.form.get('extra_days', 0))
            extra_hours = int(request.form.get('extra_hours', 0))
            extra_hours_1_5 = int(request.form.get('extra_hours_1_5', 0))
            advanced_payment = float(request.form.get('advanced_payment', 0.0))
            holidays_taken = int(request.form.get('holidays_taken', 0))

            # Save these inputs in the session temporarily
            session['days_absent'] = days_absent
            session['hours_absent'] = hours_absent
            session['extra_days'] = extra_days
            session['extra_hours'] = extra_hours
            session['extra_hours_1_5'] = extra_hours_1_5
            session['advanced_payment'] = advanced_payment
            session['holidays_taken'] = holidays_taken

            # Recalculate the updated salary after adjustments
            extra_shifts_earnings = round(extra_hours_1_5 * salary_per_hour * 1.5, 2)
            salary_after = (
                salary_before - advanced_payment - days_absent * salary_per_day -
                hours_absent * salary_per_hour + extra_days * salary_per_day +
                extra_hours * salary_per_hour + extra_shifts_earnings
            )
            salary_after = round(salary_after, 2)

            # Update session with new calculated salary
            session['salary_after'] = salary_after

            flash("Employee details updated successfully!", "success")
            return redirect(url_for('employee_details', employee_id=employee_id))
        except Exception as e:
            flash(f"An error occurred while updating the employee details: {e}", "danger")

    return render_template(
        'employee_details.html',
        employee=employee,
        month=month,
        number_of_days=number_of_days,
        salary_before=round(salary_before, 2),
        salary_per_day=salary_per_day,
        salary_per_hour=salary_per_hour,
        days_absent=days_absent,
        hours_absent=hours_absent,
        extra_days=extra_days,
        extra_hours=extra_hours,
        extra_hours_1_5=extra_hours_1_5,
        advanced_payment=round(advanced_payment, 2),
        holidays_value=holidays_value,
        extra_shifts_earnings=extra_shifts_earnings,
        salary_after=session.get('salary_after', salary_after)
    )

@app.route('/generate_pdf/<int:employee_id>', methods=['GET'])
def generate_pdf(employee_id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch the employee directly from the database using the employee ID
    employee = Employee.query.get(employee_id)

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for('employee_list'))

    try:
        # Use session values for calculations if available, otherwise fall back to defaults
        extra_hours = session.get('extra_hours', 0)
        extra_hours_1_5 = session.get('extra_hours_1_5', 0)
        extra_days = session.get('extra_days', 0)
        days_absent = session.get('days_absent', 0)
        hours_absent = session.get('hours_absent', 0)
        advanced_payment = session.get('advanced_payment', 0.0)
        salary_after = session.get('salary_after', employee.monthly_salary)

        # Calculate equivalent values
        salary_before = float(employee.monthly_salary)
        num_days = monthrange(datetime.now().year, datetime.now().month)[1]
        salary_per_day = salary_before / num_days
        salary_per_hour = salary_per_day / 9

        equivalent_normal_hours = round(extra_hours * salary_per_hour, 2)
        equivalent_hours_1_5 = round(extra_hours_1_5 * salary_per_hour * 1.5, 2)
        total_equivalent_hours = equivalent_normal_hours + equivalent_hours_1_5
        equivalent_days = round(extra_days * salary_per_day, 2)
        equivalent_days_absent = round(days_absent * salary_per_day, 2)
        equivalent_hours_absent = round(hours_absent * salary_per_hour, 2)

        # Load the PDF template
        template_path = os.path.join("static/baladna salaries.pdf")
        if not os.path.exists(template_path):
            flash("Template file not found.", "danger")
            return redirect(url_for('employee_list'))

        doc = fitz.open(template_path)
        page = doc[0]

        # Function to insert text into the PDF
        def insert_text(position, text, font_size=12, font_color=(0, 0, 0)):
            page.insert_text(position, text, fontsize=font_size, color=font_color)

        font_size = 12
        font_color = (0, 0, 0)

        # Insert relevant employee data into the PDF using session values
        insert_text((90, 263), datetime.now().strftime('%d/%m/%Y'), font_size, font_color)
        insert_text((370, 280), employee.name, font_size, font_color)
        insert_text((380, 302), employee.id_number, font_size, font_color)
        insert_text((255, 431), str(salary_before), font_size, font_color)
        insert_text((265, 479), str(extra_hours + extra_hours_1_5), font_size, font_color)
        insert_text((153, 479), f"{total_equivalent_hours:.2f}", font_size, font_color)
        insert_text((280, 527), str(extra_days), font_size, font_color)
        insert_text((160, 527), f"{equivalent_days:.2f}", font_size, font_color)
        insert_text((300, 551), str(days_absent), font_size, font_color)
        insert_text((178, 551), f"{equivalent_days_absent:.2f}", font_size, font_color)
        insert_text((273, 575), str(hours_absent), font_size, font_color)
        insert_text((161, 575), f"{equivalent_hours_absent:.2f}", font_size, font_color)
        insert_text((332, 599), str(advanced_payment), font_size, font_color)
        insert_text((254, 648), str(salary_after), font_size, font_color)

        # Save the modified PDF into a bytes buffer
        pdf_bytes = io.BytesIO()
        doc.save(pdf_bytes)
        pdf_bytes.seek(0)
        doc.close()

        # Send the generated PDF to the client
        return send_file(pdf_bytes, as_attachment=False, download_name=f"{employee.name}_details.pdf", mimetype='application/pdf')

    except Exception as e:
        print(f"Error generating PDF: {e}")
        flash("An error occurred while generating the PDF.", "danger")
        return redirect(url_for('employee_list'))

@app.route('/upload_file/<int:employee_id>', methods=['POST'])
def upload_file(employee_id):
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch the employee directly from the database using the employee ID
    employee = Employee.query.get(employee_id)

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for('employee_history', employee_id=employee_id))

    # Check if both the file and file date are provided in the request
    if 'file' not in request.files or 'file_date' not in request.form:
        flash("Please upload a file and enter the date.", "danger")
        return redirect(url_for('employee_history', employee_id=employee_id))

    file = request.files['file']
    file_date = request.form['file_date']

    # Check if a file was selected
    if file.filename == '':
        flash("No selected file", "danger")
        return redirect(url_for('employee_history', employee_id=employee_id))

    # Check if the file type is allowed
    if file and allowed_file(file.filename):
        try:
            # Read file data and save it to the database
            file_data = file.read()  # Read the file content as binary
            filename = secure_filename(file.filename)

            new_file = UploadedFile(
                employee_id=employee.id,
                filename=filename,
                file_data=file_data,
                upload_date=file_date
            )
            db.session.add(new_file)
            db.session.commit()

            flash(f"File uploaded successfully with date: {file_date}!", "success")
        except Exception as e:
            flash(f"An error occurred while processing the file: {e}", "danger")
            print(f"Error: {e}")

        return redirect(url_for('employee_history', employee_id=employee_id))
    else:
        flash("Invalid file type. Please upload a PDF or image file.", "danger")
        return redirect(url_for('employee_history', employee_id=employee_id))

@app.route('/file/<int:file_id>')
def get_file(file_id):
    uploaded_file = UploadedFile.query.get(file_id)
    if uploaded_file:
        mime_type = 'application/pdf' if uploaded_file.filename.endswith('.pdf') else 'image/jpeg'
        return send_file(
            io.BytesIO(uploaded_file.file_data),
            as_attachment=False,
            download_name=uploaded_file.filename,
            mimetype=mime_type
        )
    else:
        flash("File not found.", "danger")
        return redirect(url_for('employee_history', employee_id=uploaded_file.employee_id))


@app.route('/delete_file/<int:employee_id>/<filename>', methods=['POST'])
def delete_file(employee_id, filename):
    if 'admin' not in session:
        return redirect(url_for('login'))

    # Fetch the employee directly from the database using the employee ID
    employee = Employee.query.get(employee_id)

    if not employee:
        flash("Employee not found.", "danger")
        return redirect(url_for('employee_history', employee_id=employee_id))

    try:
        # Delete the file record from the database
        file_to_delete = UploadedFile.query.filter_by(filename=filename, employee_id=employee.id).first()
        if file_to_delete:
            db.session.delete(file_to_delete)
            db.session.commit()
            flash(f"File '{filename}' deleted successfully!", "success")
        else:
            flash(f"File '{filename}' not found.", "danger")
    except Exception as e:
        flash(f"An error occurred while deleting the file: {e}", "danger")
        print(f"Error deleting file: {e}")

    return redirect(url_for('employee_history', employee_id=employee_id))

if __name__ == '__main__':
    app.run(debug=True)
