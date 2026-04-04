# Project Logbook

Weekly entries grouped by workweek from February 24, 2026 to April 3, 2026.

## Week of February 24, 2026 to February 27, 2026

For the first 2 days, I focused on improving the initial requirements and specifications that would be given to the LLM. I was provided with a product goal and functional requirements that were still very general, so my main task was to narrow them into something clearer and more actionable. I worked on identifying exactly what the model needed to produce, what constraints it should follow, and what details could not be left open to interpretation. The goal was to make sure the LLM understood what I wanted instead of filling in gaps by choosing its own solution. This would give the project a stronger starting point and would make the expected behavior much more defined.

The project also required a web user interface. So I started brainstorming with a LLM about what the interface should have.

The rest of the week, I added in ideas such as a debate frame model (defines what a debate is about and how it is evaluated at a given point in time), I started testing and improving the user interface prompt by generaing a mock UI for myself to navigate, and looked into how a fact checking agent could be implemented into the project. 

Majority of the revision was done by asking the LLM to review and provide feedback based on a attached .txt file with the project requirements. I could also point out issues myself and ask the LLM to give multiple solutions to fix those issues.

It was important to always start a new chat for a new query/context as the chat history will be passed to the transformer and will confuse it.

## Week of March 2, 2026 to March 6, 2026

I learned about spec-driven development which differs from vibe coding in the sense that SDD focuses on structure, technical accuracy, and long-term maintenance by defining requirements first, while vibe coding emphasizes speed, rapid iteration, and experimentation through conversational prompting. I kept in mind this specific cycle throughout my project. 

My supervisor provided good feedback on the mock UI I generated and helped me notice that it was important to directly specify to the LLM that there are supposed to be multiple pages. A lot of the mock UIs I generated had everything cluttered onto a single html page which was not ideal and made it very difficult to navigate. He helped me first focus on a medium scale design (prototype) before moving on to a large scale design (product).

I tested the fact checking agent skill this week through suggestions from the LLM and refined the design specification for it as for how I wanted it to be implemented. 

Keep in mind the html mock UI designs were static and I focused on making the layout look as good as possible for now. Crucial functionalities such as admin moderation and user login still had to be implemented. 

Revisions on the UI were done by asking a LLM to do usability checks, and consistency checks. 

Being very specific is key in LLM conversations. There were many times where the LLM did something unexpected even though I assumed I gave it sufficient information.


## Week of March 9, 2026 to March 13, 2026

I began asking the LLM to create a complete runnable protoype following my completed mock UI design. Majority of the revisions were again done through reviews by the LLM.

My supervisor also introduced me to have an agent generate some auto testing scripts for itself to test whether the system meets the acceptance criteria; it should be end to end testing through the UI.  I followed advice from this article: https://www.claudecodecamp.com/p/i-m-building-agents-that-run-while-i-sleep
where the key idea was to write explicit acceptance criteria first, and then run independent verification against the real UI and only review failures.


## Week of March 30, 2026 to April 3, 2026

On the first day, I focused on creating an automated agentic workflow for the project. A big part of the work was figuring out how to structure the workflow so tasks could move more consistently from one step to the next without as much manual setup each time. I worked on defining the flow of actions, clarifying how the system should respond at each stage, and making the overall process easier to repeat. The goal was to make development more organized and efficient while giving the project a stronger foundation for future improvements.

One important thing I learned was that once the workflow is well defined, I can give the agent very high-level instructions and still get useful, structured results. For example, I can ask it to work the current system design phase and stop at the checkpoint, and it can generate the design notes, recommend the next scope decision, and wait for my approval before continuing. This makes it possible for the agent to handle most of the coding and documentation work between checkpoints while I stay focused on reviewing progress and changing requirements when needed. I also saw how logging human prompts and using scaffolding files can make the workflow more efficient, since the agent only needs to retrieve the relevant context for the current phase. Overall, this showed me how a structured workflow can turn the LLM into a much more reliable development partner.


Major UI improvements and bug fixes were completed through the agentic workflow. 







