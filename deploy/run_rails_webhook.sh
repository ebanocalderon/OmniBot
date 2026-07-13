#!/bin/bash
cd /home/chatwoot/chatwoot
export PATH="/usr/local/rvm/gems/ruby-3.4.4/bin:/usr/local/rvm/gems/ruby-3.4.4@global/bin:/usr/local/rvm/rubies/ruby-3.4.4/bin:/usr/local/rvm/bin:$PATH"
export GEM_HOME="/usr/local/rvm/gems/ruby-3.4.4"
export GEM_PATH="/usr/local/rvm/gems/ruby-3.4.4:/usr/local/rvm/gems/ruby-3.4.4@global"
export RAILS_ENV=production
/usr/local/rvm/rubies/ruby-3.4.4/bin/ruby bin/rails runner /tmp/update_telegram_webhook.rb
