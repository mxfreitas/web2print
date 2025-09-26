# Overview

Web2Print is a Flask-based web application for managing print services. Users can register, upload PDF files, and get automated cost estimates based on color analysis. The system analyzes PDFs to detect color vs monochrome pages and provides detailed pricing for different print configurations including paper types, binding options, and finishing services.

# User Preferences

Preferred communication style: Simple, everyday language.

# System Architecture

## Frontend Architecture
- **Template Engine**: Jinja2 templates with Flask
- **Styling**: Bootstrap 4.5.2 for responsive UI components
- **JavaScript**: Vanilla JavaScript for file upload handling and form interactions
- **Static Assets**: CSS organized in separate files with custom styling for print configuration forms

## Backend Architecture
- **Web Framework**: Flask with modular route handling
- **Database ORM**: SQLAlchemy for database operations
- **File Processing**: PyPDF2 and PyMuPDF (fitz) for PDF analysis and color detection
- **Session Management**: Flask sessions with configurable timeouts and security settings
- **File Upload**: Werkzeug secure filename handling

## Data Storage
- **Primary Database**: SQLite for user data, file metadata, and order configurations
- **User Model**: Comprehensive schema including personal info, file details, color analysis results, and print configuration options
- **File Storage**: Local file system for uploaded PDFs with secure filename generation

## Authentication & Authorization
- **User Authentication**: CPF-based login system
- **Session Security**: HTTP-only cookies with CSRF protection
- **User Registration**: Name, CPF, and address validation with CEP integration

## PDF Processing System
- **Color Analysis**: Automated detection of color vs monochrome pages using PyMuPDF
- **Page Counting**: Extraction of total page count from uploaded PDFs
- **Cost Estimation**: Dynamic pricing based on color analysis, paper type, binding options, and quantity

## Print Configuration Features
- **Print Types**: Color, monochrome, and mixed printing options
- **Paper Options**: Multiple paper types (sulfite, couche, recycled) with various weights
- **Binding Services**: Spiral, wire-o, hardcover, and stapling options
- **Finishing Options**: Lamination, varnish, folding services
- **Quantity Management**: Copy quantity with bulk pricing calculations

# External Dependencies

## Python Libraries
- **Flask**: Web framework for HTTP handling and routing
- **Flask-SQLAlchemy**: Database ORM for user and order management
- **PyPDF2**: PDF parsing and page extraction
- **PyMuPDF (fitz)**: Advanced PDF color analysis and content processing
- **Werkzeug**: Secure file upload handling
- **requests**: HTTP client for external API integrations (CEP validation)

## Frontend Libraries
- **Bootstrap 4.5.2**: CSS framework via CDN for responsive design
- **jQuery 3.5.1**: JavaScript library for DOM manipulation (via CDN)
- **Popper.js**: Tooltip and popover positioning (via CDN)

## External APIs
- **CEP Validation Service**: Integration for Brazilian postal code validation during user registration

## File System Dependencies
- **Upload Directory**: Local storage for PDF files with secure naming
- **Static Assets**: CSS, JavaScript, and image files served via Flask static routing

# Recent Changes & Updates

## September 26, 2025 - WooCommerce API Integration
- **New API Endpoints**: Implemented dedicated REST API endpoints for WooCommerce integration
  - `/api/v1/calculate_final`: Main endpoint for cost calculations with JSON request/response
  - `/api/v1/health`: Health check endpoint for API monitoring
- **Security Features**: Comprehensive input validation, CORS support, structured error handling
- **Integration Ready**: Full compatibility with WooCommerce REST API ecosystem and webhooks
- **Production Quality**: Robust error handling, logging, and structured JSON responses

## API Integration Features
- **Input Validation**: Complete validation of color_pages, mono_pages, paper types, weights, binding, and finishing options
- **CORS Support**: Cross-origin resource sharing configured for WooCommerce domains
- **Error Handling**: Structured error responses with specific error codes for debugging
- **Fallback Logic**: Intelligent defaults and closest-match algorithms for invalid inputs
- **Logging System**: Detailed request/response logging for integration monitoring and debugging

## WooCommerce Compatibility
- **JSON Request/Response**: Clean API interface following REST best practices
- **Flexible Parameters**: Support for optional parameters with intelligent defaults
- **Cost Breakdown**: Detailed cost structure including pages, binding, finishing, and total costs
- **Business Logic**: Direct integration with existing `calculate_advanced_cost` function using database-driven pricing