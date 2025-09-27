# Overview

Web2Print is a Flask-based web application designed to streamline print service management. It enables users to upload PDF files, receive automated cost estimates based on color analysis, and configure detailed print options. The system supports various print configurations, including paper types, binding, and finishing services, aiming to provide accurate pricing and enhance the print ordering process.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## UI/UX Decisions
-   **Frontend**: Jinja2 templates with Flask, utilizing Bootstrap 4.5.2 for responsive design and vanilla JavaScript for dynamic interactions.
-   **Styling**: Custom CSS for print configuration forms, with static assets organized logically.

## Technical Implementations
-   **Backend Framework**: Flask, featuring modular route handling and secure session management.
-   **Database ORM**: SQLAlchemy for robust interaction with a SQLite database, managing user data, file metadata, and order configurations.
-   **PDF Processing**: Advanced color detection and page counting using PyMuPDF (fitz) and PyPDF2.
-   **File Management**: Secure file uploads using Werkzeug, with local file system storage for PDFs.
-   **Authentication**: CPF-based user login with comprehensive validation and CSRF protection.
-   **Cost Estimation**: Dynamic pricing logic based on PDF analysis, selected print options (color, monochrome, mixed), paper types, binding, finishing, and quantity.

## Feature Specifications
-   **Print Configuration**: Offers extensive options for print types, diverse paper choices (sulfite, couche, recycled with various weights), binding services (spiral, wire-o, hardcover, stapling), and finishing options (lamination, varnish, folding).
-   **Quantity Management**: Includes calculations for bulk pricing based on copy quantity.

## System Design Choices
-   **Centralized PDF Analysis**: A dedicated Flask API endpoint (`/api/v1/analyze_pdf_url`) centralizes PDF processing, leveraging PyMuPDF for high-precision color detection and offering robust security features like SSRF protection and API key authentication. This ensures consistent and secure analysis across integrations.
-   **Multi-layer File Validation**: Comprehensive validation for PDF uploads, including client-side JavaScript checks, server-side WordPress validation (magic bytes, MIME type, integrity), and HTML template `accept` attributes, to ensure only valid PDFs are processed.
-   **Performance Optimizations**: Implemented a context manager for guaranteed temporary file cleanup, advanced logging for performance tracking, pre-download size verification using HEAD requests, and optimized timeouts for various operations, particularly for the Replit environment.
-   **Production-Ready Integrations**: Designed for seamless integration with WordPress/WooCommerce, including dedicated API endpoints for cost calculation (`/api/v1/calculate_final`), a WordPress plugin for PDF upload and real-time calculation, and robust metadata storage for print shop operations.

# External Dependencies

## Python Libraries
-   **Flask**: Web framework.
-   **Flask-SQLAlchemy**: ORM for database interactions.
-   **PyPDF2**: PDF parsing.
-   **PyMuPDF (fitz)**: Advanced PDF analysis and color detection.
-   **Werkzeug**: Secure file handling.
-   **requests**: HTTP client for API integrations.

## Frontend Libraries
-   **Bootstrap 4.5.2**: Responsive CSS framework (via CDN).
-   **jQuery 3.5.1**: JavaScript library (via CDN).
-   **Popper.js**: Tooltip and popover positioning (via CDN).

## External APIs
-   **CEP Validation Service**: For Brazilian postal code validation.

## File System
-   Local storage for uploaded PDF files.
-   Static assets (CSS, JavaScript, images) served via Flask.