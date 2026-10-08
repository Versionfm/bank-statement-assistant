# Bank Statement Analysis

This context describes the financial records imported from bank statements and the interpretations used to review and report them.

## Language

**Bank Account**:
An account owned by the user for which Statements and Transactions are imported.
_Avoid_: User account, login account

**Statement**:
A bank-issued document for one Bank Account and a stated period that contains transaction records and may include balance information.
_Avoid_: Monthly file, upload

**Bank Layout**:
A versioned, verified combination of bank document markers, column structure, and deterministic parsing rules. A Statement is supported only when exactly one Bank Layout is detected and registered.
_Avoid_: Bank name, PDF type

**Deterministic Parser**:
A versioned adapter that turns one verified Bank Layout into Transaction Original Values using fixed rules, never a language-model response. It rejects missing or drifted required evidence.
_Avoid_: Extraction fallback, best-effort parser

**Transaction**:
A financial movement presented in a Statement, such as an expense, income payment, fee, or transfer.
_Avoid_: Spending, row

**Counterparty**:
The normalized person or organization on the other side of a Transaction, when one can be identified from the Statement or a Correction.
_Avoid_: Merchant, payee

**Classification**:
An interpretation assigned to a Transaction by the local model or the user, comprising its Reporting Category, Movement Kind, and Payment Channel.
_Avoid_: Parsed transaction

**Reporting Category**:
A controlled grouping used to summarize a Transaction in reports. Expense categories are Groceries, Restaurants & Cafes, Housing, Utilities, Transport, Health, Insurance, Subscriptions, Shopping, Leisure, Travel, Education, Gifts & Donations, Taxes, and Other Expense; Income categories are Salary, Interest, and Other Income; Fees use Bank Fees.
_Avoid_: Purpose Category, payment method

**Unclassified**:
A review state indicating that a Transaction has no trustworthy Reporting Category yet. It is not itself a Reporting Category.
_Avoid_: Other Expense, unknown category

**Movement Kind**:
How a Transaction affects the user's finances: Expense, Income, Transfer, Refund, or Fee.
_Avoid_: Transaction type, category

**Payment Channel**:
The mechanism used for a Transaction, such as MB WAY, Card, Bank Transfer, Direct Debit, or Cash Withdrawal.
_Avoid_: Payment category, movement type

**Correction**:
A permanent record of a user-authored replacement for an extracted or classified Transaction value. The original value remains available as evidence, and reverting creates another Correction rather than erasing history.
_Avoid_: Edit, overwrite

**Correction Proposal**:
A Financial Assistant suggestion for a Correction that has no effect until the user explicitly confirms it.
_Avoid_: Automatic correction, agent edit

**Original Value**:
A value extracted from a Statement and permanently retained as source evidence, whether or not it is later corrected.
_Avoid_: Current value, editable value

**Effective Value**:
The value currently used for review and reporting: a Correction when one exists, otherwise the Original Value.
_Avoid_: Stored value, final value

**Classification Rule**:
A user-approved instruction that assigns Classification values to future matching Transactions. It takes precedence over model-generated Classification and is never created silently from a Correction.
_Avoid_: Learned correction, model training

**Statement Status**:
The current trust state of a Statement: Processing, Needs Review, Ready, or Failed. Only Ready Statements are fully trusted; Needs Review Statements may appear provisionally, while Failed Statements do not contribute to reports.
_Avoid_: Workflow status, job state

**Archived Statement**:
A Statement hidden from ordinary views while retaining its source evidence, Transactions, and history.
_Avoid_: Deleted Statement, failed Statement

**Review Finding**:
A specific validation or Classification concern that prevents part or all of a Statement from being fully trusted.
_Avoid_: Error, model opinion

**Processing Attempt**:
One execution of the Statement processing stages. Retrying creates another Processing Attempt for the same Statement rather than another Statement.
_Avoid_: Statement, duplicate import

**Monthly Report**:
A live analysis of current effective Transaction values grouped by booking-date calendar month, independent of when their Statements were imported. Corrections update the affected month rather than creating a separate report copy.
_Avoid_: Upload report, statement report

**Gross Spending**:
The total Expenses and Fees booked in a calendar month before subtracting Refunds and excluding Transfers.
_Avoid_: Total outflow, net spending

**Net Spending**:
Gross Spending minus Refunds booked in the same calendar month, excluding Transfers.
_Avoid_: Gross spending, net cash flow

**Net Cash Flow**:
Income plus Refunds minus Expenses and Fees booked in a calendar month, excluding Transfers between owned Bank Accounts.
_Avoid_: Net spending, account balance

**Reporting Currency**:
The currency in which Monthly Report totals are aggregated. The MVP Reporting Currency is EUR; Transactions in other currencies remain visible but are not converted or combined into EUR totals.
_Avoid_: Transaction currency, converted currency

**Financial Assistant**:
A conversational guide that answers questions about the user's Statements, Transactions, Corrections, and Monthly Reports using cited, trusted application data. It may create Correction Proposals but does not silently change financial data or Original Values.
_Avoid_: Chatbot, classifier
