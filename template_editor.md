Code for Homeassistant->Developer Tools->Template
Copy paste output into configuration.yaml
Adapted from https://community.home-assistant.io/t/create-generic-template/500335



template:
  - sensor:
  # Current temparature sensors (unfiltered) for all climate devices
    {%- set clim = states.climate | map(attribute='entity_id') | list %} {% for c in clim %}
    - name: {{c | regex_replace('climate.', '')}}_current_temperature_unfiltered
      state: >
        {% raw %}{{state_attr('{% endraw %}{{c}}{% raw %}', 'current_temperature')}}{%endraw%}
      unit_of_measurement: '°C'
      state_class: measurement
      availability: >
        {% raw %}{{state_attr('{%endraw%}{{c}}{%raw%}', 'current_temperature')| is_number }}{%endraw%}
    {% endfor %}

  # Target temperature for all climate devices
  {%- set clim = states.climate | map(attribute='entity_id') | list %} {% for c in clim %}
  - triggers:
      - trigger: numeric_state
        entity_id: {{c}}
        attribute: "temperature"
        above: 0
        below: 50
    sensor:
      name: {{c | regex_replace('climate.', '')}}_target_temperature
      state: >
        {% raw %}{{state_attr('{% endraw %}{{c}}{% raw %}', 'temperature')}}{%endraw%}
      unit_of_measurement: '°C'
      state_class: measurement
      availability: >
        {% raw %}{{state_attr('{%endraw%}{{c}}{%raw%}', 'temperature')| is_number }}{%endraw%}
  {% endfor %}
  
  # Current position for all cover devices
  {%- set clim = states.cover | map(attribute='entity_id') | list %} {% for c in clim %}
  - triggers:
      - trigger: numeric_state
        entity_id: {{c}}
        attribute: "current_position"
        above: 0
        below: 100
    sensor:
      name: {{c | regex_replace('cover.', '')}}_current_position
      state: >
        {% raw %}{{state_attr('{% endraw %}{{c}}{% raw %}', 'current_position')}}{%endraw%}
      unit_of_measurement: '%'
      state_class: measurement
      availability: >
        {% raw %}{{state_attr('{%endraw%}{{c}}{%raw%}', 'current_position')| is_number }}{%endraw%}
  {% endfor %}
  
  # Filter for all current position of covers
  
sensor:
  # Filter for all current climate temperatures
  {%- set clim = states.climate | map(attribute='entity_id') | list %} {% for c in clim %}
  - name: {{c | regex_replace('climate.', '')}}_current_temperature
    platform: filter  
    entity_id: sensor.{{c | regex_replace('climate.', '')}}_current_temperature_unfiltered
    filters:
      - filter: lowpass
        time_constant: 20
        precision: 2
      - filter: time_throttle
        window_size: "00:01"
  {% endfor %}
  
  