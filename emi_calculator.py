def calculate_emi(loan_amount, annual_rate, months):
    monthly_rate = annual_rate / 12 / 100

    if monthly_rate == 0:
        return loan_amount / months

    factor = (1 + monthly_rate) ** months

    emi = loan_amount * monthly_rate * factor / (factor - 1)

    return round(emi, 2)

print("Test 1:", calculate_emi(100000, 12, 12))
print("Test 2:", calculate_emi(50000, 12, 12))
print("Test 3:", calculate_emi(100000, 0, 12))



