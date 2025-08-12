from flask import Flask, render_template, request
from db import get_all_shifts

app = Flask(__name__)

@app.route("/")
def index():
    month = request.args.get("month", type=int)
    shifts = get_all_shifts()

    if month:
        shifts = [s for s in shifts if s.get("date") and s["date"].month == month]

    shifts.sort(key=lambda s: s.get("date"))

    total_salary = sum(s["salary"] for s in shifts if s.get("salary"))

    return render_template("index.html", shifts=shifts, selected_month=month, total_salary=total_salary)

if __name__ == "__main__":
    app.run(debug=True)