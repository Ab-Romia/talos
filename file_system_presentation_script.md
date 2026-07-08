# File System Section - 5 Minute Script (audience-friendly version)

About 640 words. At a calm 135-140 words per minute this lands at 4:40-4:50, leaving breathing room. Slide cues in brackets.

---

## [SLIDE: Major Requirements, File System highlighted] (0:00 - 0:20)

You have seen how Talos handles conversations. But a team's knowledge does not live in chat. It lives in files: reports, PDFs, meeting notes. So the next question was simple: how do we let people throw their documents at Talos, and have the AI actually understand them? That is the file system.

## [SLIDE: File System overview] (0:20 - 0:50)

It does four things. You upload a file. Talos processes it quietly in the background. Retrieval means the AI can answer questions using your files, and only your files. And sharing lets documents move around your team without ever becoming public. Four verbs: upload, process, retrieve, share. Everything else is detail.

## [SLIDE: File System - The Design] (0:50 - 1:45)

Under the hood there are three parts, and each one was a deliberate choice.

The files themselves live in MinIO. Think of it as our own private Amazon S3: the same technology big companies use, but it runs on our machines, it is free, and it works offline. And if Talos ever moves to the cloud, nothing needs to change, because it speaks the same language as S3.

Information about the files lives in Postgres. Every file gets an identity card: its name, its type, who uploaded it, and its current status.

And the heavy lifting happens in a background worker built on Taskiq. We actually started with a library called ARQ, but it is barely maintained anymore. The classic option, Celery, is powerful but heavy, and it was not designed for modern async Python. Taskiq gave us the best of both: lightweight, actively developed, and it fits FastAPI like a glove.

## [SLIDE: Upload Flow] (1:45 - 2:35)

So what actually happens when you drop a file into Talos? Five quick steps.

First we check the file is really what it claims to be. File names can lie; the first bytes of a file cannot.

Then the file gets its record in the database.

Now the interesting part: instead of pushing the file through our server, we hand your browser a temporary pass, and it delivers the file straight to storage. Why? Because if a hundred people upload at the same time, our server does not even notice. It never touches the bytes.

Finally, a background job is queued, and by that point Talos has already told you: done. Upload feels instant, because the slow part has not happened yet.

## [SLIDE: Processing Pipeline] (2:35 - 3:15)

The slow part happens here, where nobody is waiting for it.

The worker picks up the file and reads it. For reading we chose one library, called unstructured, that understands PDFs, Word documents, and plain notes, instead of juggling a separate reader for every format.

The text is then cut into small overlapping pieces, because AI models read paragraphs, not entire books.

Each piece is stored in Milvus. Why Milvus and not our normal database? Because Milvus searches by meaning, not by keywords. Ask about vacation rules, and it finds the paragraph about annual leave policy. When all this finishes, the file simply shows up as Ready.

## [SLIDE: Storage and Sharing] (3:15 - 3:45)

Two nice things fall out of this design.

All storage sits behind one door. That is why adding Google Drive import was a plug-in, not a rewrite.

And downloads use expiring links. Think of them as visitor badges: safe to hand out, useless to steal, expired by tomorrow.

## [SLIDE: Challenges and Solutions] (3:45 - 4:40)

Of course, none of this worked on the first try. A quick tour of what broke.

Our download links pointed to addresses that only existed inside Docker, so browsers could not open them. We split private and public addresses.

Anyone can rename virus.exe into report.pdf. We read the real bytes, so names cannot lie to us.

Deleted files kept haunting the AI's answers. Now, deleting a file wipes its memory too.

Google Drive logins expired in the middle of a session. Now they renew themselves.

Thousands of files made lists crawl. We load them page by page, so it stays fast at any size.

And when file processing crashes, the job retries on its own and records the error. Nothing fails silently.

## [SLIDE: File System in Action] (4:40 - 5:00)

And this is not a mockup. This is Talos running live: real documents, uploaded through exactly the flow you just saw, all processed and marked Ready. From this moment, these files are part of what the AI knows, and that is exactly where the next section, AI and RAG, picks up.

---

## Practice notes

- The comparisons are your "we are engineers" moments: MinIO vs cloud S3, Taskiq vs ARQ and Celery, Milvus vs a normal database. Say them casually, like decisions you argued about, because you did.
- Punchlines to pause after: "file names can lie; the first bytes cannot", "upload feels instant because the slow part has not happened yet", "visitor badges", "deleting a file wipes its memory too".
- If someone asks for numbers: pieces are about 1000 characters with 200 overlap, uploads up to 50 MB, formats are PDF, DOCX, TXT, MD, plus images.
- If someone asks "why not Celery" in Q&A: Celery needs more infrastructure and configuration, and its async support is bolted on; Taskiq is async from the ground up, which matches FastAPI.
