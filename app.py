import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import plotly.express as px

# Load external CSS file
def load_css(css_file):
    with open(css_file, "r", encoding="utf-8") as f:
        st.markdown(f'<style>{f.read()}</style>', unsafe_allow_html=True)


class Database:
    def __init__(self, db_file="expense_splitter.db"):
        """Initialize the database connection and create tables if they don't exist."""
        self.db_file = db_file
        self.conn = None
        self.connect()
        self.create_tables()
    
    def connect(self):
        """Establish a connection to the SQLite database."""
        self.conn = sqlite3.connect(self.db_file, check_same_thread=False)
        
    def create_tables(self):
        """Create the necessary tables if they don't exist."""
        cursor = self.conn.cursor()
        
        # Create Person table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS person (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        
        # Create Category table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS category (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            )
        ''')
        
        # Create Expense table with category
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expense (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                description TEXT NOT NULL,
                amount REAL NOT NULL,
                date TEXT NOT NULL,
                paid_by INTEGER NOT NULL,
                category_id INTEGER,
                FOREIGN KEY (paid_by) REFERENCES person(id),
                FOREIGN KEY (category_id) REFERENCES category(id)
            )
        ''')
        
        # Create ExpenseSplit table
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS expense_split (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                expense_id INTEGER NOT NULL,
                person_id INTEGER NOT NULL,
                share_amount REAL NOT NULL,
                FOREIGN KEY (expense_id) REFERENCES expense(id) ON DELETE CASCADE,
                FOREIGN KEY (person_id) REFERENCES person(id)
            )
        ''')
        
        # Insert default categories if not exists
        default_categories = ["Food", "Shopping", "Beauty", "Travel", "Entertainment", "Other"]
        for category in default_categories:
            cursor.execute('INSERT OR IGNORE INTO category (name) VALUES (?)', (category,))
        
        self.conn.commit()
        
        # Check if the category_id column exists in the expense table
        cursor.execute("PRAGMA table_info(expense)")
        columns = [column[1] for column in cursor.fetchall()]
        
        # If migrating from an older version without category_id, ensure all tables match the schema
        if "category_id" not in columns:
            # Backup existing data
            cursor.execute("ALTER TABLE expense RENAME TO expense_old")
            
            # Create new table with correct schema
            cursor.execute('''
                CREATE TABLE expense (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    amount REAL NOT NULL,
                    date TEXT NOT NULL,
                    paid_by INTEGER NOT NULL,
                    category_id INTEGER,
                    FOREIGN KEY (paid_by) REFERENCES person(id),
                    FOREIGN KEY (category_id) REFERENCES category(id)
                )
            ''')
            
            # Migrate data (using default category 6 for "Other")
            cursor.execute('''
                INSERT INTO expense (id, description, amount, date, paid_by, category_id)
                SELECT id, description, amount, date, paid_by, 6 FROM expense_old
            ''')
            
            # Drop old table
            cursor.execute("DROP TABLE expense_old")
            
            self.conn.commit()
    
    def close(self):
        """Close the database connection."""
        if self.conn:
            self.conn.close()


class ExpenseSplitterApp:
    def __init__(self):
        """Initialize the Expense Splitter App."""
        st.set_page_config(page_title="Cutie Expense Splitter", page_icon="🎀")
        # Load external CSS instead of applying inline styles
        load_css("style.css")
        self.db = Database()
    
    
    def add_person(self, name):
        """Add a new person to the database."""
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('INSERT INTO person (name) VALUES (?)', (name,))
            self.db.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    
    def get_all_persons(self):
        """Get all persons from the database."""
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT id, name FROM person ORDER BY name')
        return cursor.fetchall()
    
    def get_all_categories(self):
        """Get all categories from the database."""
        cursor = self.db.conn.cursor()
        cursor.execute('SELECT id, name FROM category ORDER BY name')
        return cursor.fetchall()
    
    def add_expense(self, description, amount, date, paid_by, category_id, splits):
        """Add a new expense and its splits to the database."""
        cursor = self.db.conn.cursor()
        try:
            # Add expense
            cursor.execute('''
                INSERT INTO expense (description, amount, date, paid_by, category_id)
                VALUES (?, ?, ?, ?, ?)
            ''', (description, amount, date, paid_by, category_id))
            
            expense_id = cursor.lastrowid
            
            # Add splits
            for person_id, share_amount in splits.items():
                cursor.execute('''
                    INSERT INTO expense_split (expense_id, person_id, share_amount)
                    VALUES (?, ?, ?)
                ''', (expense_id, person_id, share_amount))
            
            self.db.conn.commit()
            return True
        except sqlite3.Error as e:
            st.error(f"Database error: {str(e)}")
            return False
    
    def get_all_expenses(self):
        """Get all expenses with their payer information."""
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('''
                SELECT e.id, e.description, e.amount, e.date, p.name, c.name
                FROM expense e
                JOIN person p ON e.paid_by = p.id
                LEFT JOIN category c ON e.category_id = c.id
                ORDER BY e.date DESC
            ''')
            return cursor.fetchall()
        except sqlite3.Error as e:
            st.error(f"Error fetching expenses: {str(e)}")
            return []
    
    def delete_expense(self, expense_id):
        """Delete an expense from the database."""
        cursor = self.db.conn.cursor()
        try:
            cursor.execute('DELETE FROM expense_split WHERE expense_id = ?', (expense_id,))
            cursor.execute('DELETE FROM expense WHERE id = ?', (expense_id,))
            self.db.conn.commit()
            return True
        except sqlite3.Error:
            return False
    
    def calculate_balances(self):
        """Calculate the current balances between all people."""
        cursor = self.db.conn.cursor()
        
        # Get all persons
        cursor.execute('SELECT id, name FROM person')
        persons = cursor.fetchall()
        
        balances = {}
        for person in persons:
            person_id, person_name = person
            balances[person_id] = {'name': person_name, 'balance': 0}
        
        # Calculate what each person paid
        cursor.execute('''
            SELECT paid_by, SUM(amount) as total_paid
            FROM expense
            GROUP BY paid_by
        ''')
        payments = cursor.fetchall()
        
        for paid_by, total_paid in payments:
            balances[paid_by]['balance'] += total_paid
        
        # Calculate what each person owes
        cursor.execute('''
            SELECT person_id, SUM(share_amount) as total_share
            FROM expense_split
            GROUP BY person_id
        ''')
        shares = cursor.fetchall()
        
        for person_id, total_share in shares:
            balances[person_id]['balance'] -= total_share
        
        return balances
    
    def calculate_settlements(self, balances):
        """Calculate the optimal settlement transactions."""
        # Extract people with positive and negative balances
        creditors = []  # People who should receive money
        debtors = []    # People who should pay money
        
        for person_id, data in balances.items():
            if data['balance'] > 0:
                creditors.append((person_id, data['name'], data['balance']))
            elif data['balance'] < 0:
                debtors.append((person_id, data['name'], abs(data['balance'])))
        
        # Sort by amount (descending)
        creditors.sort(key=lambda x: x[2], reverse=True)
        debtors.sort(key=lambda x: x[2], reverse=True)
        
        # Calculate transactions
        transactions = []
        
        i, j = 0, 0
        while i < len(creditors) and j < len(debtors):
            creditor_id, creditor_name, amount_to_receive = creditors[i]
            debtor_id, debtor_name, amount_to_pay = debtors[j]
            
            amount = min(amount_to_receive, amount_to_pay)
            transactions.append((debtor_name, creditor_name, amount))
            
            # Update balances
            creditors[i] = (creditor_id, creditor_name, amount_to_receive - amount)
            debtors[j] = (debtor_id, debtor_name, amount_to_pay - amount)
            
            # Move to next person if their balance is settled
            if creditors[i][2] < 0.01:  # Small threshold for floating point errors
                i += 1
            if debtors[j][2] < 0.01:
                j += 1
        
        return transactions
    
    def run(self):
        """Run the Expense Splitter App."""
        
        st.title(" Expense Splitter ")
        st.markdown("#### Split expenses with your besties! 👯‍♀️")
        
        # Sidebar navigation with cute emojis
        page = st.sidebar.radio("Navigation", 
                               ["✨ Add Friend", "💖 Add Expense", "🌸 View Expenses", "💝 Settle Up"],
                               index=0)
        
        if page == "✨ Add Friend":
            self.show_add_person()
        
        elif page == "💖 Add Expense":
            self.show_add_expense()
        
        elif page == "🌸 View Expenses":
            self.show_view_expenses()
        
        elif page == "💝 Settle Up":
            self.show_settle_up()
    
    def show_add_person(self):
        """Show the add person form."""
        st.header("👯‍♀️ Add New Friend")
        with st.form("add_person_form"):
            name = st.text_input("Friend's Name")
            if st.form_submit_button("Add Friend ✨"):
                if name:
                    if self.add_person(name):
                        st.success(f"🎉 Added {name} successfully! You're the best!")
                    else:
                        st.error(f"🎀 Friend with name '{name}' already exists.")
                else:
                    st.error("🎀 Please enter a name.")
        
        # Show existing people
        st.subheader("Your Besties")
        persons = self.get_all_persons()
        if persons:
            df = pd.DataFrame(persons, columns=["ID", "Name"])
            st.dataframe(df)
        else:
            st.info("No friends added yet. Add your besties to get started! 💕")
    
    def show_add_expense(self):
        """Show the add expense form."""
        st.header("💸 Add New Expense")
        st.markdown("##### Track your shopping sprees and brunches!")
        persons = self.get_all_persons()
        categories = self.get_all_categories()
        
        if not persons:
            st.warning("⚠️ Please add some friends first!")
            return
        
        with st.form("add_expense_form"):
            description = st.text_input("What did you buy?")
            
            col1, col2 = st.columns(2)
            with col1:
                amount = st.number_input("Amount (₹)", min_value=0.01, value=100.00, step=10.0)
            with col2:
                date = st.date_input("Date")
            
            paid_by = st.selectbox(
                "Who paid? 💳",
                options=[p[0] for p in persons],
                format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
            )
            
            category = st.selectbox(
                "Category 🛍️",
                options=[c[0] for c in categories],
                format_func=lambda x: next((c[1] for c in categories if c[0] == x), "")
            )
            
            st.subheader("Split between 👭")
            
            # Default to equal split
            split_method = st.radio(
                "Split method",
                ["Equal split 💕", "Custom split ✨"]
            )
            
            involved = st.multiselect(
                "Who's involved?",
                options=[p[0] for p in persons],
                default=[p[0] for p in persons],
                format_func=lambda x: next((p[1] for p in persons if p[0] == x), "")
            )
            
            splits = {}
            
            if split_method == "Equal split 💕" and involved:
                share = amount / len(involved)
                for person_id in involved:
                    splits[person_id] = share
                
                st.info(f"💖 Each person pays: ₹{share:.2f}")
            
            elif split_method == "Custom split ✨" and involved:
                st.write("Enter custom amounts for each person:")
                total_assigned = 0
                
                for person_id in involved:
                    person_name = next((p[1] for p in persons if p[0] == person_id), "")
                    share = st.number_input(
                        f"{person_name}'s share",
                        min_value=0.0,
                        max_value=float(amount),
                        value=amount / len(involved),
                        step=10.0,
                        key=f"share_{person_id}"
                    )
                    splits[person_id] = share
                    total_assigned += share
                
                # Validate total matches amount
                if abs(total_assigned - amount) > 0.01:
                    st.warning(f"Total split amount (₹{total_assigned:.2f}) doesn't match expense amount (₹{amount:.2f})")
            
            if st.form_submit_button("Add Expense 💝"):
                if not description:
                    st.error("🎀 Please enter a description.")
                elif amount <= 0:
                    st.error("🎀 Amount must be greater than zero.")
                elif not involved:
                    st.error("🎀 Please select at least one friend to split with.")
                elif split_method == "Custom split ✨" and abs(sum(splits.values()) - amount) > 0.01:
                    st.error("🎀 Total split amount must equal the expense amount.")
                else:
                    if self.add_expense(description, amount, date.strftime("%Y-%m-%d"), paid_by, category, splits):
                        st.success("🎉 Expense added successfully! You're amazing!")
                    else:
                        st.error("🎀 Failed to add expense.")
    
    def show_view_expenses(self):
        """Show all expenses with ability to filter and delete."""
        st.header("🌸 All Expenses")
        st.markdown("##### Track all your fun purchases!")
        
        try:
            expenses = self.get_all_expenses()
            
            if expenses:
                # Add filter options
                st.subheader("✨ Filter Expenses")
                persons = self.get_all_persons()
                categories = self.get_all_categories()
                
                col1, col2 = st.columns(2)
                with col1:
                    person_filter = st.selectbox(
                        "Filter by friend",
                        options=[None] + [p[0] for p in persons],
                        format_func=lambda x: "All Friends" if x is None else next((p[1] for p in persons if p[0] == x), ""),
                    )
                
                with col2:
                    category_filter = st.selectbox(
                        "Filter by category",
                        options=[None] + [c[0] for c in categories],
                        format_func=lambda x: "All Categories" if x is None else next((c[1] for c in categories if c[0] == x), ""),
                    )
                
                # Apply filters
                filtered_expenses = expenses
                if person_filter:
                    person_name = next((p[1] for p in persons if p[0] == person_filter), "")
                    filtered_expenses = [e for e in filtered_expenses if e[4] == person_name]
                
                if category_filter:
                    category_name = next((c[1] for c in categories if c[0] == category_filter), "")
                    filtered_expenses = [e for e in filtered_expenses if e[5] == category_name]
                
                if filtered_expenses:
                    df = pd.DataFrame(
                        filtered_expenses,
                        columns=["ID", "Description", "Amount", "Date", "Paid By", "Category"]
                    )
                    df["Amount"] = "₹" + df["Amount"].astype(str)
                    st.dataframe(df)
                    
                    # Delete expense option
                    selected_expense = st.selectbox(
                        "Select an expense to delete:",
                        options=[e[0] for e in filtered_expenses],
                        format_func=lambda x: f"{next((e[1] for e in filtered_expenses if e[0] == x), '')} - ₹{next((e[2] for e in filtered_expenses if e[0] == x), 0)}"
                    )
                    
                    if st.button("Delete Selected Expense 🗑️"):
                        if self.delete_expense(selected_expense):
                            st.success("Expense deleted successfully! You're so organized!")
                            st.rerun()
                        else:
                            st.error("Failed to delete expense.")
                else:
                    st.info("No expenses match your filters. Try something else! 💕")
            else:
                st.info("💝 No expenses found. Add some fun spending to get started!")
        except Exception as e:
            st.error(f"Error viewing expenses: {str(e)}")
    
    def show_settle_up(self):
        """Show current balances and settlement options."""
        st.header("💰 Settle Up With Friends")
        st.markdown("##### Keep your friendships happy! 👯‍♀️")
        
        try:
            balances = self.calculate_balances()
            
            if balances:
                # Show current balances
                st.subheader("💖 Current Balances")
                balance_data = []
                for person_id, data in balances.items():
                    balance_data.append({
                        "Friend": data['name'],
                        "Balance": data['balance'],
                        "Status": "Gets back 💝" if data['balance'] > 0 else "Owes 💸" if data['balance'] < 0 else "Settled ✨"
                    })
                
                df_balances = pd.DataFrame(balance_data)
                df_balances["Display Balance"] = df_balances["Balance"].apply(lambda x: f"₹{x:.2f}")
                
                # Display balance dataframe
                st.dataframe(df_balances[["Friend", "Display Balance", "Status"]])
                
                # Calculate and show settlement plan
                st.subheader("💕 Suggested Settlements")
                transactions = self.calculate_settlements(balances)
                
                if transactions:
                    for debtor, creditor, amount in transactions:
                        st.info(f"💸 {debtor} pays {creditor} ₹{amount:.2f}")
                else:
                    st.success("✨ Everyone is settled up! Best friends forever!")
                
                # Mark as settled option
                st.subheader("🌸 Mark as Settled")
                st.warning("💝 This will reset balances for selected friends. Use with love!")
                
                persons = self.get_all_persons()
                settle_person = st.selectbox(
                    "Select friend to mark as settled:",
                    options=[None] + [p[0] for p in persons],
                    format_func=lambda x: "Select a friend" if x is None else next((p[1] for p in persons if p[0] == x), "")
                )
                
                if settle_person and st.button("Mark as Settled 💖"):
                    cursor = self.db.conn.cursor()
                    cursor.execute('UPDATE expense_split SET share_amount = 0 WHERE person_id = ?', (settle_person,))
                    cursor.execute('UPDATE expense SET amount = 0 WHERE paid_by = ?', (settle_person,))
                    self.db.conn.commit()
                    st.success(f"Balance for {next((p[1] for p in persons if p[0] == settle_person), '')} marked as settled! You're such a good friend!")
                    st.rerun()

            else:
                st.info("💝 No balances found. Add some shopping trips to get started!")
        except Exception as e:
            st.error(f"Error in settle up: {str(e)}")


# Run the app when the script is executed
if __name__ == "__main__":
    app = ExpenseSplitterApp()
    app.run()