# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

# Claude Project Configuration

This project uses a two-agent system: an Architect and a Coder.
Each agent operates in a separate Claude Code session with its own role file.

## How to load each agent
**Architect session:**
When the human says "You are the Architect":
- Read `agents/architect.md`
- Read `agents/handoff.md`
- Confirm you are in Architect mode before responding

**Coder session:**
When the human says "You are the Coder":
- Read `agents/coder.md`
- Read `agents/handoff.md`
- Confirm the spec is approved before proceeding
- Confirm you are in Coder mode before responding

Do not wait to be told which files to read. Loading the role files is automatic on role activation.

## The handoff document

`handoff.md` is the shared document both agents read and write to.
- The Architect writes the spec and decisions into it
- The Coder reads from it and implements against it
- Both agents write questions and responses to each other in it

## When to switch sessions

- Need design decisions, structural review, or tradeoff analysis -> Architect session
- Have an approved spec and are ready to implement -> Coder session
- Coder has questions mid-implementation -> Coder writes to handoff.md, human switches to Architect session and says "read handoff.md, answer the coder questions"

## Project context

We are building a middleware software integration between our on-premise WHM software QuikPAK, our on-premise ERP (Sage 300), our cloud-based courier integration platform (ShipStation) and UPS. The middleware reads a pair of XML files from QuikPAK for each shipment, gets additional data from Sage 300 SQL database, posts orders in ShipStation, then retrieves the courier information and tracking number from ShipStation, additional multi-package tracking numbers from UPS, and finally writes a matching pair of XML files back to the local server for each shipment.
