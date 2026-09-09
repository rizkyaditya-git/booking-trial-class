# Trial booking system

<!-- In one or two sentences, say what this project does and who it is for. -->

## Progress

- [ ] A parent can choose a child and an available trial class.
- [ ] A parent can submit a trial booking.
- [ ] The system records a mock payment result.
- [ ] The parent can see the booking status.
- [ ] An admin or teacher can view the confirmed roster.
- [ ] A child cannot have duplicate confirmed bookings for one class.
- [ ] A class cannot have more than four confirmed students.
- [ ] A failed payment does not add the child to the confirmed roster.
- [ ] At most one competing payment can claim the last seat.

## How to run it

<!-- Add prerequisites, setup, environment variables, database setup, seed steps, and the exact command that starts the app. Only include commands you have run. -->

```sh
# Fill in during implementation.
```

## What I built

<!-- Describe the parent booking flow, mock payment flow, booking status, and admin or teacher roster. Keep regular enrollment out of scope. -->

## Seed data and demo cases

<!-- Explain how to load the synthetic data and identify these cases: a class with available seats, a class with three confirmed students, a duplicate attempt, and a failed payment. -->

## Backend design

### Data model

<!-- List the tables or collections, their important fields, and the relationships between them. -->

### Backend entry points

<!-- List the API endpoints, server actions, or functions used by the booking and roster flows. State what each one accepts and returns. -->

### Booking statuses

<!-- List each status and the allowed transitions. Explain when a booking enters the confirmed roster. -->

### Rules and where they are enforced

<!-- Explain which checks run in the UI, backend, database, or a background job. Cover duplicate confirmation, the four-student cap, and payment failure. -->

### Last-seat race

<!-- Explain how confirmation rechecks capacity atomically. Include the approach, why you chose it, what happens to the losing payment, and the tradeoffs you accepted. -->

## Tests and verification

<!-- Add the exact test and lint commands you ran, followed by their results. Cover duplicate confirmation, payment failure, capacity, and two payment completions racing for the last seat. -->

```sh
# Fill in after running each check.
```

## Assumptions

<!-- Record assumptions that affected the implementation. -->

## Time spent

<!-- Record the total time and, if useful, a short breakdown. Keep the work within the four-hour limit. -->

## Scope cuts and tradeoffs

<!-- List what you deliberately left out and why. Include unfinished work instead of expanding the scope. -->

## What I would monitor

<!-- Describe the production signals you would watch, such as booking failures, payment outcomes, duplicate attempts, or capacity conflicts. Name only signals supported by your final design. -->

## What I would do next

<!-- List the first improvements you would make with more time. -->

## Video walkthrough

<!-- Add the public link to the 5 to 8 minute walkthrough. -->
