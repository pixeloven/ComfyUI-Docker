#!/bin/bash
set -e

# Source logging functions
source "$(dirname "$0")/scripts/lib/logging.sh"

# Function to run all post-install scripts
run_post_install_scripts() {
    log_info "Starting post-install script execution..."
    
    local total_scripts=0
    
    # Execute numbered scripts in order from scripts root directory
    for script in ./scripts/[0-9]*.sh; do
        # Skip if no scripts match the pattern
        [ ! -f "$script" ] && continue
        
        log_info "Executing script: $(basename "$script")"
        
        # Run the script and capture exit code, but let output show
        "$script"
        local exit_code=$?
        
        if [ $exit_code -eq 0 ]; then
            log_success "Script completed: $(basename "$script")"
            ((total_scripts++))
        else
            log_error "Script failed: $(basename "$script")"
            return 1
        fi
    done
    
    if [ $total_scripts -eq 0 ]; then
        log_warning "No scripts found to execute"
    else
        log_success "All $total_scripts post-install scripts completed successfully"
    fi
}

# Function to check if post-install has been completed
check_post_install_status() {
    log_info "Checking post-install completion status..."
    
    if [ -f .post_install_done ]; then
        log_success "Post-install steps already completed."
        return 0
    else
        log_info "Post-install steps not completed, proceeding with installation."
        return 1
    fi
}

# Function to mark post-install as complete
mark_post_install_complete() {
    touch .post_install_done
    log_success "Post-install steps marked as complete."
}

# Check and run post-install scripts if needed
if ! check_post_install_status; then
    if run_post_install_scripts; then
        mark_post_install_complete
    else
        log_error "Post-install scripts failed, exiting..."
        exit 1
    fi
fi

# Show comfy environment
comfy env

# Disable tracking (optional)
comfy tracking disable

# Start ComfyUI with the specified parameters (uses /app by default)
comfy launch -- --listen --port $COMFY_PORT $CLI_ARGS 